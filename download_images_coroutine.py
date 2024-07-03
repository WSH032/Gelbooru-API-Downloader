"""Created on Fri May 19 23:26:50 2023

@author: WSH
"""

import argparse
import asyncio
import hashlib
import logging
import math
import os
import time
from asyncio import Task
from collections import deque
from enum import IntEnum
from typing import Any, Dict, List, Literal, NamedTuple, Optional, Tuple, Union
from urllib.parse import urlencode

import aiofiles
import aiofiles.os
import httpx
from pydantic import BaseModel, ConfigDict, Field
from tqdm import tqdm
from typing_extensions import Annotated

from utils.check_images import check_images

__all__ = (
    "BASE_URL",
    "BASE_URL_PARAMS",
    "DownloadResult",
    "DownloadResultState",
    "Downloader",
    "GetAPI",
    "launch_executor",
    "scrape_images",
)


# see: https://gelbooru.com/index.php?page=wiki&s=view&id=18780
BASE_URL = "https://gelbooru.com/index.php"
BASE_URL_PARAMS = {
    "page": "dapi",
    "json": 1,
    "s": "post",
    "q": "index",
}
SHOW_URL_PARAMS = {
    "page": "post",
    "s": "list",
    "q": "index",
}

WAITING_TIME_BEFORE_DOWNLOADING = 3  # 下载前等待时间(s)


##############################


class DownloadResultState(IntEnum):
    """下载结果枚举"""

    ERROR = 0
    """下载失败"""
    SUCCESS = 1
    """下载成功"""
    DUPLICATE = 2
    """已有重复文件"""


class DownloadResult(NamedTuple):
    """用于记录Downloader.download下载的结果"""

    state: DownloadResultState
    """下载结果枚举"""
    path: str
    """下载的文件路径"""
    start_time: Union[float, int]
    """下载开始时间戳，单位为秒"""
    end_time: Union[float, int]
    """下载结束时间戳，单位为秒"""
    size: int
    """下载的文件大小，单位为字节.
        注意，这里指的是确实下载的文件大小，如果重复文件，则应该为0。
    """
    tags: Optional[str] = None
    """下载的图片的tag字符串"""
    md5: Optional[str] = None
    """下载的文件的md5值"""

    def __eq__(self, other: object):
        """为了向前兼容，方便用 DownloadResult() == 1 等判断下载结果"""
        return self.state == other

    def __bool__(self):
        """为了向前兼容，方便用 if DownloadResult() 等判断下载结果"""
        return bool(self.state)

    def __str__(self):  # noqa: D105
        return f"\
DownloadResult(state={self.state}, \
path={self.path}, \
start_time={self.start_time}, \
end_time={self.end_time}, \
size={self.size}, \
tags={self.tags}, \
md5={self.md5})"

    def __repr__(self):  # noqa: D105
        return self.__str__()


### 下载类 Downloader ###


async def _get_response_to_file(
    file_path: str,
    file_url: str,
    async_client: httpx.AsyncClient,
    timeout: Optional[Union[int, float]] = None,
) -> Literal[0, 1]:
    """异步、流式地连接中地连接 `file_url` ，将回应内容写入到 `file_path`.

    Args:
        file_path: 写入文件路径
        file_url: 文件url链接
        async_client: 用于连接的 `httpx.AsyncClient`
        timeout: get请求超时限制，`None` 则不限时. Defaults to None.

    Returns:
        成功下载返回1， 出现异常返回0
    """
    try:
        # 进行连接
        async with async_client.stream("GET", file_url, timeout=timeout) as r:
            # 检查是否是200成功访问,不是就引发异常
            r.raise_for_status()

            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in r.aiter_bytes():
                    if chunk:
                        await f.write(chunk)
        return 1

    except Exception as e:
        logging.error(f"下载 {file_url} 时发生错误, error: {e}")
        return 0


async def _tags2txt(tags: str, txt_path: str) -> Literal[0, 1]:
    """异步地将 `tags` 的内容写入 `txt_path`

    Args:
        tags: 字符串内容
        txt_path: 写入路径

    Returns:
        成功返回1， 异常返回0
    """
    try:
        async with aiofiles.open(txt_path, "w") as f:
            await f.write(tags)
        return 1

    except Exception as e:
        logging.error(f"将tags写入 {txt_path} 时发生错误, error: {e}")
        return 0


def _check_download_state(
    task_result_list: List[Union[BaseException, Literal[0, 1]]],
) -> DownloadResultState:
    # 如果结果不都为1，即返回了0或者异常。 就返回0
    if [result for result in task_result_list if result != 1]:
        return DownloadResultState.ERROR

    # 如果只有一个任务，说明存在重复文件而没下载图片。返回2
    if len(task_result_list) == 1:
        return DownloadResultState.DUPLICATE

    # 上述两种情况都没发生，说明正常下载了图片和tags。 返回1
    return DownloadResultState.SUCCESS


class Downloader:
    """下载器"""

    def __init__(
        self,
        timeout: Optional[Union[int, float]],
        semaphore: Optional[asyncio.Semaphore],
        async_client: httpx.AsyncClient,
    ):
        """下载器

        Args:
            timeout: 超时限制，单位为秒
            semaphore: 用于控制并发数的信号量
            async_client: 用于发送下载请求的 `httpx.AsyncClient`
        """
        self.timeout = timeout
        self.semaphore = semaphore
        self.async_client = async_client

    @staticmethod
    async def cul_md5(file_path: str):
        """计算文件的 MD5 哈希值

        file_path为需要计算的文件路径

        只有成功计算了哈希值才返回，否则就返回None
        """
        try:
            async with aiofiles.open(file_path, "rb") as f:
                md5_hash = hashlib.md5()
                while True:
                    chunk = await f.read(128 * 1024)  # 128kb
                    if not chunk:
                        break
                    await asyncio.to_thread(md5_hash.update, chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            logging.error(f"检验 {file_path} md5时发生错误 error: {e}")
            return None

    async def download(  # noqa: C901, PLR0912
        self,
        download_dir: str,
        file_url: str,
        file_name: Optional[str] = None,
        tags: Optional[str] = None,
        md5: Optional[str] = None,
    ) -> DownloadResult:
        """下载文件和将tags写入文本.

        Note: 无论是否有重复有文件，tags都会被重写一次

        Args:
            download_dir: 下载地址，这个必须是已经存在的路径.
            file_url: 文件链接url.
            file_name: 文件名字，`None` 则使用下载连接的 `basename`. Defaults to None.
            tags: tags字符串，`None` 则不保存tags文本. Defaults to None.
            md5: 文件的md5字符串，`None`则不进行重复哈希校验 . Defaults to None.

        Raises:
            Exception: _description_

        Returns:
            返回一个DownloadResult对象，记录下载结果
        """
        # 如果没提供文件名，就用url中的basename
        if file_name is None:
            file_name = os.path.basename(file_url)
        file_path = os.path.join(download_dir, file_name)

        # 获取初始化参数
        timeout = self.timeout
        semaphore = self.semaphore
        async_client = self.async_client

        # 如果提供了如果提供了md5，则尝试进行重复校验
        # 如果检查到已经存在的本地文件md5和提供一致，就不下载图片了
        is_duplicate = False
        if md5 is not None:
            try:
                if (
                    await aiofiles.os.path.exists(file_path)
                    and await Downloader.cul_md5(file_path) == md5
                ):
                    is_duplicate = True
            except Exception as e:
                logging.error(f"校验md5时发生错误。 error : {e}")
        # 如果传入了semaphore，则根据其限制下载并发数
        if semaphore is not None:
            await semaphore.acquire()

        try:
            task_list: List[Task[Literal[0, 1]]] = []
            # 如果不存在重复文件，准备创建下载任务
            if not is_duplicate:
                file_task = asyncio.create_task(
                    _get_response_to_file(
                        file_path, file_url, async_client=async_client, timeout=timeout
                    )
                )
                task_list.append(file_task)

            # 不管图片是否重复，只要提供了tasg输入参数，创建写入tag文件任务
            if tags is not None:
                txt_path = os.path.join(
                    download_dir, os.path.splitext(file_name)[0] + ".txt"
                )
                tags_task = asyncio.create_task(_tags2txt(tags, txt_path))
                task_list.append(tags_task)

            # 同步等待任务完成
            wait_start = time.time()
            task_result_list = await asyncio.gather(*task_list, return_exceptions=True)
            wait_end = time.time()

            state = _check_download_state(task_result_list)

            # 如果存在重复文件，说明根本没下载，下载量自然为0
            if state is DownloadResultState.DUPLICATE:
                size = 0
            # 成功下载；或者错误，但是可能也下载了一部分，所以也返回文件大小
            else:
                # 如果文件存在，获取文件大小，否则就是0
                try:
                    size = await aiofiles.os.path.getsize(file_path)
                except Exception:
                    size = 0

            download_result = DownloadResult(
                state=state,
                path=file_path,
                start_time=wait_start,
                end_time=wait_end,
                size=size,
                tags=tags,
                md5=md5,
            )
            return download_result

        # 遇到异常
        except Exception as e:
            raise Exception(f"创建 {file_name} 协程任务时发生错误, error: {e}") from e

        finally:
            if semaphore is not None:
                semaphore.release()


##############################


class _Attributes(BaseModel):
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]
    count: Annotated[int, Field(ge=0)]


class _Post(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    md5: str
    file_url: str
    tags: str
    image: str


class _GelbooruApiJson(BaseModel):
    """Gelbooru API返回的json格式"""

    attributes: Annotated[_Attributes, Field(alias="@attributes")]
    post: List[_Post]


def _get_api_post_data(response: httpx.Response) -> Optional[List[_Post]]:
    """从响应中获取post信息"""
    response.raise_for_status()  # 检查是否是200成功访问,不是就引发异常
    # 读取JSON格式的返回信息，只取其中post部分
    api_data = _GelbooruApiJson.model_validate_json(response.text)
    post_api_date = api_data.post

    # 只有确实获取到了信息，才返回数据，否则返回None
    if post_api_date:
        return post_api_date
    else:
        return None


# API类 GetAPI
class GetAPI:
    """API查询器"""

    def __init__(
        self,
        async_client: httpx.AsyncClient,
        base_url: str,
        base_url_params: Dict[str, Any],
    ):
        """初始化GetAPI参数

        Args:
            async_client: 用于连接的 `httpx.AsyncClient`
            base_url: 访问的域名
            base_url_params: 访问的API url参数
        """
        self.base_url = base_url
        self.base_url_params = base_url_params
        self.async_client = async_client

    async def get_api(
        self,
        tags: str,
        limit: int = 100,
        pid: int = 0,
    ) -> Optional[List[_Post]]:
        """根据tags获取gelbooru的API信息

        Args:
            tags: 需要查询的tags
            limit: 一次获取图片的最大限制. Defaults to 100.
            pid: 查询的页数索引. Defaults to 0.

        Returns:
            - 如果成功获取图片信息，就返回Api中所包含的post图片信息
            - 如果不成功就返回None
        """
        api_param: Dict[str, Any] = {
            "limit": limit,
            "tags": tags,
            "pid": pid,
        }

        # 获取初始化参数
        base_url = self.base_url
        base_url_params = self.base_url_params
        async_client = self.async_client

        try:
            response = await async_client.get(
                base_url, params=base_url_params | api_param
            )
            return _get_api_post_data(response)
        except Exception as e:
            logging.error(f"{e}")
            return None


##############################
# 计算下载速度，会被launch_executor使用
class _DownloadSpeed:
    """根据n个记录点和初始点，计算瞬时和平均下载速度"""

    def __init__(
        self,
        n: int,
        data_size_init: int = 0,
        time_init: float = 0,
    ):
        """根据n个记录点和初始点，计算瞬时和平均下载速度

        Args:
            n: 用于计算平均数的数据个数
            data_size_init: 开始之前已有的下载量. Defaults to 0.
            time_init: 开始时间戳. Defaults to 0.
        """
        self._n = n
        self._data_size_init = data_size_init
        self._time_init = time_init

        # 注意，这里需要计算n个数据，并且需要一个初始点，所以需要n+1个数据
        _data_n = self._n + 1
        self._data = deque(
            ((self._data_size_init, self._time_init) for i in range(_data_n)),
            _data_n,
        )
        self._instant_speed = 0  # 初始瞬时速度为0
        self._average_speed = 0  # 初始平均速度为0

    def set_init(
        self,
        data_size_init: Optional[int] = None,
        time_init: Optional[float] = None,
    ) -> None:
        """将数据状态重置为初始

        如有需要，可以改变以下参数：
        data_size_init为需要修改的开始之前下载量
        time_init为需要修改的开始时间戳
        """
        # 调用__init__重新初始化
        # 如果没有传入参数，就使用原来的参数
        self.__init__(
            n=self._n,
            data_size_init=self._data_size_init
            if data_size_init is None
            else data_size_init,
            time_init=self._time_init if time_init is None else time_init,
        )

    def update(self, data_size: int, time: float) -> None:
        """更新数据

        data_size为某个时间点对应的总下载数据的大小，speed将保持和这里输入一样的单位
        time为data_size对应的时间点
        """
        # 在头部插入新元素, 因为deque有长度限制，所以会自动顶出最后一个元素
        self._data.appendleft((data_size, time))

    def speed(self) -> Tuple[float, float]:
        """根据n个记录点和初始点，计算瞬时和平均下载速度，返回每秒大小，单位为输入update的单位.

        返回一个元组，第一个元素为瞬时速度，第二个元素为平均速度
        """
        data_size_list, time_list = zip(*self._data)
        data_size_list = list(data_size_list)
        time_list = list(time_list)

        self._instant_speed = (max(data_size_list) - min(data_size_list)) / (
            max(time_list) - min(time_list)
        )
        self._average_speed = (max(data_size_list) - self._data_size_init) / (
            max(time_list) - self._time_init
        )
        return self._instant_speed, self._average_speed


def _byte_to_mb(byte: Union[int, float]) -> float:
    """将byte单位转换为MB单位"""
    # 1048576 = 1024 * 1024
    return byte / 1048576


# 协程池调度器
async def launch_executor(
    post_data: List[_Post],
    download_dir: str,
    max_workers: int,
    timeout: Optional[Union[int, float]],
    async_client: httpx.AsyncClient,
) -> "_DownloadInfoTuple":
    """并发下载，将 `post_data` 的每一份分给一个协程.

    Args:
        post_data: 下载信息.
        download_dir: 下载目录.
        max_workers: 并发数.
        timeout: 下载超时时间，单位为秒.
            注意这个实现是靠子函数 `download_file` 中的httpx库实现
            如果其中一个线程下载超时无响应，就会引发一个错误被捕获，并返回1
        async_client: 用于下载的`httpx.AsyncClient.

    Raises:
        e: 任意一个下载任务发生错误时引发，为 `Exception`

    Returns:
        成功会返回一个元组，按顺序为：总下载任务、 成功下载数、 存在的重复数、 下载失败数
    """
    # 实例化下载器
    downloader = Downloader(
        timeout=timeout,
        semaphore=asyncio.Semaphore(max_workers),
        async_client=async_client,
    )

    # 创建下载task
    tasks_list: List[Task[DownloadResult]] = []
    for post in post_data:
        coroutine = downloader.download(
            download_dir,
            post.file_url,
            file_name=post.image,
            tags=post.tags,
            md5=post.md5,
        )
        tasks_list.append(asyncio.create_task(coroutine))

    # 用于统计下载计数
    all_download_number = len(post_data)
    successful_download_number = 0
    duplicate_download_number = 0
    error_download_number = 0

    # 用于统计下载速度，其采用平均算法，因为有max_workers个并发，所以需要对max_workers个数据取平均
    download_speed = _DownloadSpeed(max_workers)

    try:
        # 注意，这个time_init是第一个任务开始时候的时间戳，所以这个set_init应该传入开始瞬间的time.time()
        download_speed.set_init(time_init=time.time())

        # 等待结果
        download_pbar = tqdm(
            asyncio.as_completed(tasks_list), total=all_download_number
        )
        total_download_size = 0
        for task in download_pbar:
            try:
                res = (
                    await task
                )  # 读取已经完成的结果,不会阻塞其他协程，但是本协程会同步阻塞

                # 统计下载结果
                _state = res.state
                if _state is DownloadResultState.ERROR:
                    error_download_number += 1
                elif _state is DownloadResultState.SUCCESS:
                    successful_download_number += 1
                elif _state is DownloadResultState.DUPLICATE:
                    duplicate_download_number += 1
                else:
                    error_download_number += 1
                    logging.error(f"任务 {task} 返回状态异常, result: {res}")

                # 更新下载速度
                total_download_size += res.size  # 总下载量
                download_speed.update(
                    total_download_size, res.end_time
                )  # 每个时间点对应的累计下载量
                instant_speed, average_speed = (
                    download_speed.speed()
                )  # 计算瞬时和平均下载速度

                # 转为MB单位
                instant_speed_mb = _byte_to_mb(instant_speed)
                average_speed_mb = _byte_to_mb(average_speed)
                total_download_size_mb = _byte_to_mb(total_download_size)

                download_pbar.set_description(
                    f"当前: {instant_speed_mb:.2f}MB/s，平均: {average_speed_mb:.2f}MB/s，总量: {total_download_size_mb:.2f}MB"
                )
            except Exception as e:
                error_download_number += 1
                logging.error(f"任务 {task} 返回状态异常, error: {e}")

        # 统计下载信息
        download_info = _DownloadInfoTuple(
            all_download_number,
            successful_download_number,
            duplicate_download_number,
            error_download_number,
        )

        tqdm.write("下载完成")
        tqdm.write(f"下载任务： {download_info.all} 个")
        tqdm.write(f"成功完成： {download_info.success} 个")
        tqdm.write(f"存在重复： {download_info.duplicate} 个")
        tqdm.write(f"下载失败： {download_info.error} 个")

        return download_info

    except Exception as e:
        logging.error(f"下载 {post_data[0:5]} 时发生错误, error: {e}")
        # 发生异常时，取消全部未完成的下载任务
        for task in tasks_list:
            task.cancel()
        raise


##############################


class _DownloadInfoTuple(NamedTuple):
    all: int
    success: int
    duplicate: int
    error: int


class _DownloadInfoCounter:
    """用于下载计数的类"""

    def __init__(self):
        """初始化所有计数为0"""
        self.all = 0
        self.success = 0
        self.duplicate = 0
        self.error = 0

    def update(self, download_info_tuple: _DownloadInfoTuple):
        """更新下载计数"""
        if download_info_tuple:
            self.all += download_info_tuple.all
            self.success += download_info_tuple.success
            self.duplicate += download_info_tuple.duplicate
            self.error += download_info_tuple.error

    def print(self):
        """按顺序输出相关信息"""
        print("*#" * 20)
        print("下载总结")
        print(f"下载任务： {self.all} 个")
        print(f"成功完成： {self.success} 个")
        print(f"存在重复： {self.duplicate} 个")
        print(f"下载失败： {self.error} 个")


def _process_tags(
    tags: str,
    add_comma: bool,
    remove_underscore: bool,
    use_escape: bool,
) -> str:
    """处理tags字符串，返回处理后的字符串"""
    tag_list = tags.split(" ")
    # 忽略emoji，将_替换为空格
    if remove_underscore:
        for i, tag in enumerate(tag_list):
            if len(tag) > 3:  # ignore emoji tags like >_< and ^_^
                tag_list[i] = tag.replace("_", " ")
    # 转义正则表达式特殊字符
    if use_escape:
        for i, tag in enumerate(tag_list):
            if len(tag) > 3:  # ignore emoji tags like >_< and ^_^
                tag_list[i] = tag.replace("(", "\\(").replace(")", "\\)")
    # 添加', '分割或者' '分割
    final_tags = ", ".join(tag_list) if add_comma else " ".join(tag_list)
    return final_tags


# 顶层封装
async def scrape_images(
    tags: str,
    max_images_number: int,
    download_dir: str,
    max_workers: int = 10,
    unit: int = 100,
    timeout: Optional[Union[int, float]] = 10,
    add_comma: bool = True,
    remove_underscore: bool = True,
    use_escape: bool = True,
    check_images_mode: Union[None, int] = None,
) -> None:
    r"""从gelbooru抓取图片，图片数量为max_images_number以unit为单位向上取.

    Args:
        tags: 用于在gelbooru中搜索图片的tag，浏览以下链接获取更多信息.
            - [tags](https://gelbooru.com/index.php?page=wiki&s=&s=view&id=25921)
            - [cheatsheet](https://gelbooru.com/index.php?page=wiki&s=&s=view&id=26263)
        max_images_number: 要抓取的图片数量.
        download_dir: 下载目录.
        max_workers: 下载并发数. Defaults to 10.
        unit: 下载量单位，最小为1，最大为100. Defaults to 100.
        timeout: 单个图片下载超时限制，单位为秒. Defaults to 10.
        add_comma: 是否在`与图片一起被抓取的tag字符串`中添加逗号分割. Defaults to True.
        remove_underscore: 是否将`与图片一起被抓取的tag字符串`中的下划线换成空格. Defaults to True.
        use_escape: 是否对`与图片一起被抓取的tag字符串`中的成空格进行转义. Defaults to True.
            即 `()` -> `\(` 和 `)` -> `\)`.
        check_images_mode: 是否在下载结束后检查图片是否正确. Defaults to None.
            - None: 不检查
            - 0: 检查，但只输出信息不做任何操作
            - 1: 尝试修复图片
            - 2: 尝试删除图片

    Returns:
        None
    """
    # 尝试用ipython展示markdown连接
    show_url = BASE_URL + "?" + urlencode(SHOW_URL_PARAMS | {"tags": tags})
    print(f"打开此连接检查图片是否正确: {show_url}")

    # 建立连接客户端
    async with httpx.AsyncClient() as async_client:
        # 尝试连接并读取json格式
        test_response = await async_client.get(
            BASE_URL, params=BASE_URL_PARAMS | {"tags": tags}
        )
        test_response.raise_for_status()

        try:
            test_api_data = _GelbooruApiJson.model_validate_json(test_response.text)
        except Exception as e:
            raise AssertionError("无法获取正确的json格式") from e

        count = test_api_data.attributes.count
        if count == 0:
            print("未发现任何图像，检查下输入的tags")
            return

        limit = max(1, min(100, unit))  # 每页获取图片数，最小为1，最大100
        max_pid = math.floor(count / limit)  # 根据图片总数，计算最大可访问页数
        need_pid = math.floor(
            (max_images_number - 1) / limit
        )  # 根据输入的max_images_numbe，决定要访问的页数
        # 最终决定下载的轮数，不超过最大可访问页数，如果读不到图片就不下载
        download_count = min(max_pid, need_pid) + 1  # `+1` 是因为页数从0开始

        print(f"找到 {count} 张图片")
        print(f"指定下载 {max_images_number} 张, 将执行 { download_count } 轮下载")
        print(f"下载将在 {WAITING_TIME_BEFORE_DOWNLOADING} 秒后开始")

        # 下载前读秒
        for t in range(WAITING_TIME_BEFORE_DOWNLOADING):
            print(WAITING_TIME_BEFORE_DOWNLOADING - t)
            await asyncio.sleep(1)

        # 下载计数器
        download_info_counter = _DownloadInfoCounter()

        # 实例化GetAPI类用于查询API， 提供先前的async_client， 将在此函数执行完后才关闭
        get_api = GetAPI(
            base_url=BASE_URL,
            base_url_params=BASE_URL_PARAMS,
            async_client=async_client,
        )

        # 创建下载文件夹
        await aiofiles.os.makedirs(download_dir, exist_ok=True)

        for i in range(download_count):
            # print下载轮次
            divide_str = "#" * 20  # 显示每轮之间的分割字符
            tqdm.write(f"{divide_str}\n第 {i+1} / {download_count} 轮下载进行中:")

            # 查询API
            api_post_data = await get_api.get_api(tags, limit=limit, pid=i)

            if api_post_data is not None:
                for post in api_post_data:
                    post.tags = _process_tags(
                        post.tags,
                        add_comma=add_comma,
                        remove_underscore=remove_underscore,
                        use_escape=use_escape,
                    )

                res = await launch_executor(
                    api_post_data,
                    download_dir,
                    max_workers=max_workers,
                    timeout=timeout,
                    async_client=async_client,
                )
                download_info_counter.update(res)
            else:
                tqdm.write("第 {i+1} 轮下载失败")
            await asyncio.sleep(0.5)  # 休息一下，减轻压力

        download_info_counter.print()

        if check_images_mode not in [0, 1, 2, None]:
            logging.warning(
                "check_images_mode 参数错误，其值将被置为None，且不进行检查"
            )
            check_images_mode = None
        # 是否删除下载失败的图片
        if check_images_mode is not None:
            delete_list = await asyncio.to_thread(  # noqa: F841
                check_images,
                download_dir,
                max_workers=None,
                mode=check_images_mode,
                debug=True,
            )


##############################
# 命令行脚本
if __name__ == "__main__":
    """ 用命令行读取参数并启动下载协程 """

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--tags", type=str, default="girl", help="符合gelbooru规则的tags字符串"
    )
    parser.add_argument(
        "--max_images_number", type=int, default="50", help="下载图片数量"
    )
    parser.add_argument(
        "--download_dir",
        type=str,
        default=os.path.join(os.getcwd(), "images"),
        help="下载路径",
    )
    parser.add_argument("--max_workers", type=int, default=15, help="最大协程工作数")
    parser.add_argument(
        "--unit", type=int, default=50, help="下载单位，图片数量以此向上取一单位"
    )
    parser.add_argument("--timeout", type=int, default=10, help="连接超时限制")
    parser.add_argument(
        "--add_comma", action="store_true", help="是否在tags之间添加逗号"
    )
    parser.add_argument(
        "--remove_underscore",
        action="store_true",
        help="是否将tags中的下划线替换为空格",
    )
    parser.add_argument(
        "--use_escape", action="store_true", help="是否转义正则表达式特殊字符"
    )
    parser.add_argument(
        "--check_images_mode",
        type=int,
        default=None,
        help="None为不检查，0表示只检查并输出信息而不做任何操作，1表示检查并尝试修复图片，2表示检查并删除无法读取的图片",
    )

    cmd_param, unknown = parser.parse_known_args()

    if unknown:
        logging.error(f"以下输入参数非法，将被忽略：\n{unknown}")

    tags = cmd_param.tags
    max_images_number = cmd_param.max_images_number
    download_dir = cmd_param.download_dir
    max_workers = cmd_param.max_workers
    unit = cmd_param.unit
    timeout = cmd_param.timeout
    add_comma = cmd_param.add_comma
    remove_underscore = cmd_param.remove_underscore
    use_escape = cmd_param.use_escape
    check_images_mode = cmd_param.check_images_mode

    Scrape_images_coroutine = scrape_images(
        tags,
        max_images_number,
        download_dir,
        max_workers=max_workers,
        unit=unit,
        timeout=timeout,
        add_comma=add_comma,
        remove_underscore=remove_underscore,
        use_escape=use_escape,
        check_images_mode=check_images_mode,
    )

    asyncio.run(Scrape_images_coroutine)
