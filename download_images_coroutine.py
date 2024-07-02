# -*- coding: utf-8 -*-
"""
Created on Fri May 19 23:26:50 2023

@author: WSH
"""


from utils.check_images import check_images
import httpx
import aiofiles
import aiofiles.os
import hashlib
import logging
import asyncio
import os
from tqdm import tqdm
import pandas as pd
from urllib.parse import urlencode
import math
import argparse
from typing import Tuple, Union, Optional
import time

##############################
class DownloadResult(object):
    """用于记录Downloader.download下载的结果"""
    # 可能需要补上一个url属性，以后再说
    def __init__(self,
                 state: int,
                 path: str,
                 start_time: Union[float, int, None]=None,
                 end_time: Union[float, int, None]=None,
                 size: Optional[int]=None,
                 tags: Optional[str]=None,
                 md5: Optional[str]=None,
        ):
        """
        state : 下载结果
        path : 下载的文件路径
        start_time  : 下载开始时间戳，单位为秒
        end_time  : 下载结束时间戳，单位为秒
        size : 下载的文件大小,单位为字节；是确实下载的文件大小，如果重复文件，则应该为0
        tags : 下载的tags内容
        md5 : 下载的文件的md5值
        """
        self.state = state
        self.path = path
        self.start_time = start_time 
        self.end_time = end_time
        self.size = size
        self.tags = tags
        self.md5 = md5

    def __eq__(self, other):
        """ 为了向前兼容，方便用 DownloadResult() == 1 等判断下载结果 """
        if isinstance(other, DownloadResult):
            return self.state == other.state
        elif isinstance(other, int):
            return self.state == other
        else:
            raise TypeError(f"unsupported operand type(s) for ==: '{type(self)}' and '{type(other)}'")
    
    def __bool__(self):
        """ 为了向前兼容，方便用 if DownloadResult() 等判断下载结果 """
        return bool(self.state)

    def __str__(self):
        return f"\
DownloadResult(state={self.state}, \
path={self.path}, \
start_time={self.start_time}, \
end_time={self.end_time}, \
size={self.size}, \
tags={self.tags}, \
md5={self.md5})"

    def __repr__(self):
        return self.__str__()


### 下载类 Downloader ###
class Downloader(object):

    def __init__(self,
            timeout=None,
            semaphore=None,
            async_client=None,
    ):
        """
        async_client : httpx库的异步客户端
        timeout : 超时限制，单位为秒，留空则不限时
        semaphore : 为协程池控制类，留空则不限制并发数
        """

        self.param = {}
        self.param["timeout"]=timeout
        self.param["semaphore"]=semaphore
        self.param["async_client"]=async_client
    
    @staticmethod
    async def cul_md5(file_path):
        """
        计算文件的 MD5 哈希值
        
        file_path为需要计算的文件路径
        
        只有成功计算了哈希值才返回，否则就返回None
        """

        try:
            async with aiofiles.open(file_path, 'rb') as f:
                md5_hash = hashlib.md5()
                while True:
                    chunk = await f.read(128*1024)  # 128kb
                    if not chunk:
                        break
                    await asyncio.to_thread( md5_hash.update, chunk )
            return md5_hash.hexdigest()
        except Exception as e:
            logging.error(f"检验 {file_path} md5时发生错误 error: {e}")
            return None


    async def download(self,
                        download_dir,
                        file_url,
                        file_name=None,
                        tags=None,
                        md5=None,
    ) -> DownloadResult:
        """
        下载文件和将tags写入文本

        download_dir : 下载地址，这个必须是已经存在的路径
        file_url : 文件连接
        file_name : 文件名字，留空则使用下载连接basename
        tags : tags字符串，留空则不保存tags文本
        md5 : 文件的md5字符串,留空则不进行重复哈希校验

        返回一个DownloadResult对象，记录下载结果
        （无论是否有重复有文件，tags都会被重写一次）
        下载结果：
            下载失败就返回0
            下载成功返回1
            已有重复文件返回2
            遇到异常会引发一个Exception
        """
        
        # 如果没提供文件名，就用url中的basename
        if file_name is None:
            file_name = os.path.basename(file_url)
        file_path = os.path.join(download_dir, file_name)


        # 获取初始化参数
        timeout = self.param.get("timeout")
        semaphore = self.param.get("semaphore")  # 引用是相同的
        async_client = self.param.get("async_client")  # 引用是相同的


        # 如果提供了如果提供了md5，则尝试进行重复校验
        # 如果检查到已经存在的本地文件md5和提供一致，就不下载图片了
        is_duplicate = False
        if md5 is not None:
            try:
                if await aiofiles.os.path.exists(file_path):
                    # 类方法，异步
                    if await Downloader.cul_md5(file_path) == md5:
                        is_duplicate = True
            except Exception as e:
                logging.error(f"校验md5时发生错误。 error : {e}")


        # 函数 ######################################################################
        async def get_response_to_file(file_path,
                        file_url,
                        async_client=None,
                        timeout=None
        ):
            """
            异步、流式地连接中地连接file_url，将回应内容写入到file_path

            response应为async_client.stream()返回的流式对象
            file_path为写入路径
            async_client为异步客户端，如果不提供则会新建一个
            timeout为get请求超时限制，不提供则不限时

            成功下载返回1， 出现异常返回0
            """

            # 如果初始化的时候没传入异步客户端，就新建一个； 如果传了，就用传入的
            if async_client is None:
                used_client = httpx.AsyncClient()
            else:
                used_client = async_client

            try:
                # 进行连接
                async with used_client.stream("GET", file_url, timeout=timeout) as r:

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

            finally:
                # 如果是新建的异步客户端，就关闭
                if async_client is None:
                    await used_client.aclose()

        
        async def tags2txt(tags, txt_path):
            """
            异步地将tags的内容写入txt_path

            tags为字符串内容
            txt_path为写入路径

            成功返回1， 异常返回0
            """
            try:
                async with aiofiles.open(txt_path, "w") as f:
                    await f.write(tags)
                return 1
            
            except Exception as e:
                logging.error(f"将tags写入 {txt_path} 时发生错误, error: {e}")
                return 0


        # 如果传入了semaphore，则根据其限制下载并发数
        if semaphore is not None:
            await semaphore.acquire()

        try:    
            task_list = []
            # 如果不存在重复文件，准备创建下载任务
            if not is_duplicate:
                file_task = asyncio.create_task( get_response_to_file(file_path, file_url, async_client=async_client, timeout=timeout) )
                task_list.append(file_task)

            # 不管图片是否重复，只要提供了tasg输入参数，创建写入tag文件任务
            if tags is not None:
                txt_path = os.path.join(download_dir, os.path.splitext(file_name)[0] + ".txt")
                tags_task = asyncio.create_task( tags2txt(tags, txt_path) )
                task_list.append(tags_task)
            
            # 同步等待任务完成
            wait_start = time.time()
            task_result_list = await asyncio.gather( *task_list, return_exceptions=True )
            wait_end = time.time()

            def judge_download_state(task_result_list: list):
                
                # 如果结果不都为1，即返回了0或者异常。 就返回0
                if [result for result in task_result_list if result != 1 ]:
                    return 0
                
                # 在1不成时，如果只有一个任务，说明存在重复文件而没下载图片。返回2
                if len(task_result_list) == 1:
                    return 2

                # 上述两种情况都没发生，说明正常下载了图片和tags。 返回1
                return 1
            
            state = judge_download_state(task_result_list)

            # 如果存在重复文件，说明根本没下载，下载量自然为0
            if state == 2:
                size = 0
            # 成功下载；或者错误，但是可能也下载了一部分，所以也返回文件大小
            else:
                 # 如果文件存在，获取文件大小，否则就是0
                try:
                    size = await aiofiles.os.path.getsize(file_path)
                except:
                    size = 0
            
            download_result = DownloadResult(state = state,
                                            path = file_path,
                                            start_time = wait_start,
                                            end_time = wait_end,
                                            size = size,
                                            tags = tags,
                                            md5 = md5,
                                )
            return download_result
        
        # 遇到异常
        except Exception as e:
            raise Exception(f"创建 {file_name} 协程任务时发生错误, error: {e}") from e
        
        finally:
            if semaphore is not None:
                semaphore.release()      


##############################
# API类 GetAPI
class GetAPI(object):
    
    base_url = 'https://gelbooru.com/index.php'
    base_url_params = {'page': 'dapi',
        'json': 1,
        's': 'post',
        'q': 'index',
    }

    def __init__(self, base_url=base_url, base_url_params=base_url_params, async_client=None):
        """
        初始化GetAPI参数

        base_url为访问的域名， 如果不提供则采用类属性
        base_url_params为访问的API url参数， 如果不提供则采用类属性
        async_client为用于连接的httpx.AsyncClient类， 如果不提供则使用get_api时会新建一个
        """
        self.param = {}
        self.param["base_url"] = base_url
        self.param["base_url_params"] = base_url_params
        self.param["async_client"] = async_client
         

    async def get_api(self, tags: str, limit: int=100, pid: int=0,):
        """
        根据tags获取gelbooru的API信息
        
        tags为需要查询的tags
        limit为一次获取图片的最大限制
        pid为页数

        如果成功获取图片信息，就返回一个pandas.DataFrame
        如果不成功就返回None
        """

        api_param = {'limit': limit,
                'tags': tags,
                'pid': pid,
        }

        #获取初始化参数
        base_url = self.param["base_url"]
        base_url_params = self.param["base_url_params"]
        # 如果初始化的时候没传入异步客户端，就新建一个； 如果传了，就用传入的
        async_client = httpx.AsyncClient() if self.param["async_client"] is None else self.param["async_client"]

        try:
            response = await async_client.get( base_url, params=base_url_params|api_param )
            def get_df(response):
                """ 从响应中获取post信息 """
                response.raise_for_status()  # 检查是否是200成功访问,不是就引发异常
                # 读取JSON格式的返回信息，只取其中post部分
                response_dict = response.json()

                df = pd.DataFrame ( response_dict.get( 'post', [] ) )
                # 只有确实获取到了信息，才返回一个非空的pd.Dataframe，否则返回None
                if not df.empty:
                    return df
                else:
                    return None
            return get_df(response)
        
        except Exception as e:
            logging.error(f"{e}")
            return None
        
        finally:
            # 如果是新建的异步客户端，就关闭
            if self.param.get("async_client") is None:
                await async_client.aclose()


##############################
# 计算下载速度，会被launch_executor使用
class DownloadSpeed(object):
    """ 根据n个记录点和初始点，计算瞬时和平均下载速度 """
    def __init__(self,
                 n: int,
                 data_size_init: int=0,
                 time_init: float=0,
        ):
        """
        n为计算平均的数据个数
        data_size_init为开始之前下载量
        time_init为开始时间戳
        """
        self._n = n
        self._data_size_init = data_size_init
        self._time_init = time_init

        # 注意，这里需要计算n个数据，并且需要一个初始点，所以需要n+1个数据
        self._data = [ (self._data_size_init, self._time_init) for i in range(self._n + 1) ]
        self._instant_speed = 0  # 初始瞬时速度为0
        self._average_speed = 0  # 初始平均速度为0
    
    def set_init(self,
                 data_size_init: Optional[int]=None,
                 time_init: Optional[float]=None,
        ):
        """
        将数据状态重置为初始
        
        如有需要，可以改变以下参数：
        data_size_init为需要修改的开始之前下载量
        time_init为需要修改的开始时间戳
        """

        # 调用__init__重新初始化
        # 如果没有传入参数，就使用原来的参数
        self.__init__(n = self._n,
                      data_size_init = self._data_size_init if data_size_init is None else data_size_init,
                      time_init = self._time_init if time_init is None else time_init,
        )

    
    def update(self, data_size: int, time: float):
        """
        更新数据
        data_size为某个时间点对应的总下载数据的大小，speed将保持和这里输入一样的单位
        time为data_size对应的时间点
        """

        # 删除掉最后一个元素，在头部插入新元素
        self._data.pop()
        self._data.insert(0, (data_size, time))

    def speed(self) -> Tuple[float, float]:
        """
        根据n个记录点和初始点，计算瞬时和平均下载速度
        返回每秒大小，单位为输入update的单位

        返回一个元组，第一个元素为瞬时速度，第二个元素为平均速度
        """

        data_size_list = [ data_size for data_size, _ in self._data ]
        time_list = [ time for _, time in self._data ]

        self._instant_speed = ( max(data_size_list) - min(data_size_list) ) / ( max(time_list) - min(time_list) )
        self._average_speed = ( max(data_size_list) - self._data_size_init ) / ( max(time_list) - self._time_init )
        return self._instant_speed, self._average_speed

# 协程池调度器
async def launch_executor(files_df,
              download_dir: str,
              max_workers: int=10,
              timeout :int=10,
              async_client=None,
    ):
    """
    多线程下载，将files_df的每一行分给一个协程
    
    files_df为包含了下载信息的panda.DataFrame
    download_dir为下载目录
    max_workers为并发数
    timeout为下载超时时间，单位为秒
        注意这个实现是靠子函数download_file中的httpx库实现
        如果其中一个线程下载超时无响应，就会引发一个错误被捕获，并返回1
    async_client为httpx.AsyncClient异步客户端类， 如果不提供就新建一个线程池运行完后就关闭的客户端
    
    成功会返回一个元组，按顺序为：总下载任务、 成功下载数、 存在的重复数、 下载失败数
    如果发生异常，则会引发原异常
    """
    # 使用协程来调度下载任务
    semaphore = asyncio.Semaphore(max_workers)

    # 如果初始化的时候没传入异步客户端，就新建一个； 如果传了，就用传入的
    if async_client is None:
        used_client = httpx.AsyncClient()
    else:
        used_client = async_client

    # 实例化下载器
    downloader = Downloader(timeout=timeout, semaphore=semaphore, async_client=used_client)

    # 创建下载task
    tasks_list = []
    for row in files_df.itertuples():
        coroutine = downloader.download(download_dir,
                        row.file_url,
                        file_name=row.image,
                        tags=row.tags,
                        md5=row.md5,
        )
        tasks_list.append( asyncio.create_task(coroutine) )

    # 用于统计下载计数
    all_download_number = len(files_df)
    successful_download_number = 0
    duplicate_download_number = 0
    error_download_number = 0

    # 用于统计下载速度，其采用平均算法，因为有max_workers个并发，所以需要对max_workers个数据取平均
    download_speed = DownloadSpeed( max_workers )

    try:
        # 注意，这个time_init是第一个任务开始时候的时间戳，所以这个set_init应该传入开始瞬间的time.time()
        download_speed.set_init( time_init=time.time() )

        # 等待结果
        download_pbar = tqdm( asyncio.as_completed(tasks_list), total=all_download_number )
        total_download_size = 0
        for task in download_pbar:
            try:
                res = await task  # 读取已经完成的结果,不会阻塞其他协程，但是本协程会同步阻塞
                if res == 0:
                    error_download_number += 1
                elif res == 1:
                    successful_download_number += 1
                elif res == 2:
                    duplicate_download_number += 1
                else:
                    error_download_number += 1
                    logging.error(f"任务 {task} 返回状态异常, result: {res}")
                # 更新下载速度
                total_download_size += res.size  # 总下载量
                download_speed.update(total_download_size, res.end_time)  # 每个时间点对应的累计下载量
                instant_speed, average_speed = download_speed.speed()  # 计算瞬时和平均下载速度

                # 转为MB单位
                instant_speed_mb = instant_speed/1024/1024
                average_speed_mb = average_speed/1024/1024
                total_download_size_mb = total_download_size/1024/1024

                download_pbar.set_description(f"当前: {instant_speed_mb:.2f}MB/s，平均: {average_speed_mb:.2f}MB/s，总量: {total_download_size_mb:.2f}MB")

            except Exception as e:
                error_download_number += 1
                logging.error(f"任务 {task} 返回状态异常, error: {e}")
        # 统计下载信息
        download_info = ( all_download_number, successful_download_number, duplicate_download_number,  error_download_number )

        tqdm.write("下载完成")
        tqdm.write(f"下载任务： {download_info[0]} 个")
        tqdm.write(f"成功完成： {download_info[1]} 个")
        tqdm.write(f"存在重复： {download_info[2]} 个")
        tqdm.write(f"下载失败： {download_info[3]} 个")
        
        return download_info
    
    except Exception as e:
        logging.error(f"下载 {files_df.head()} 时发生错误, error: {e}")
        # 发生异常时，取消全部未完成的下载任务
        for task in tasks_list:
            task.cancel()
        raise e
    
    finally:
        # 如果是新建的异步客户端，就关闭
        if async_client is None:
            await used_client.aclose()
            
            
##############################
# 顶层封装
async def Scrape_images(tags :str,
                        max_images_number: int,
                        download_dir :str,
                        max_workers :int=10,
                        unit: int=100,
                        timeout :int=10,
                        add_comma :bool=True,
                        remove_underscore: bool=True,
                        use_escape: bool=True,
                        check_images_mode: Union[None, int]=None,
                        base_url=None,
                        base_url_params=None,
                        show_url_params=None,
):
    """
    从gelbooru抓取图片，图片数量为max_images_number以unit为单位向上取
    
    tags为要抓取的tag字符串
    max_images_number为要抓取的图片数量
    download_dir为下载目录
    max_workers为下载线程
    unit为下载块单位，最小为1，最大为100
    timeout为单个图片下载超时限制，单位为秒
    add_comma为是否在tag字符串中添加逗号
    remove_underscore为是否将下划线换成空格
    use_escape为是否对'(' ')'进行转义为'\\(' '\\)'
    check_images_mode为是否在下载结束后检查图片是否正确
        默认为None，不检查
        0为检查，但只输出信息不做任何操作
        1为尝试修复图片
        2为尝试删除图片
    
    无返回值
    """

    # 基础api参数，如果没输入则使用默认参数
    if base_url is None:
        base_url = 'https://gelbooru.com/index.php'
    if base_url_params is None:
        base_url_params = {'page': 'dapi',
                    'json': 1,
                    's': 'post',
                    'q': 'index',
        }
    if show_url_params is None:
        show_url_params = {'page': 'post',
                    's': 'list',
                    'q': 'index',
        }

    # 尝试用ipython展示markdown连接
    show_url = base_url + '?' + urlencode( show_url_params|{"tags":tags} )
    try:
        from IPython.display import display, Markdown  # type: ignore
        display(Markdown(f"[点击检查图片是否正确]({show_url})"))
    except Exception:
        pass
    
    print(f"打开此连接检查图片是否正确: {show_url}")
        
    
    # 建立连接客户端
    async with httpx.AsyncClient() as async_client:
        # 尝试连接并读取json格式
        test_response = await async_client.get( base_url, params=base_url_params|{"tags":tags} )
        test_response.raise_for_status()
        test_response_dict = test_response.json()

        # 尝试从回应中获取数量
        count = test_response_dict.get("@attributes",{}).get("count",0)
        limit = max(1, min(100, unit) )  # 每页获取图片数，最小为1，最大100
        max_pid = math.floor( count / limit )  # 根据图片总数，计算最大可访问页数
        need_pid = math.floor( (max_images_number-1) / limit )  # 根据输入的max_images_numbe，决定要访问的页数
        # 最终决定下载的轮数，不超过最大可访问页数，如果读不到图片就不下载
        download_count = min(max_pid, need_pid) + 1 if count != 0 else 0
        wait_time = 3  # 下载前开始等待秒数

        if download_count == 0:
            print("未发现任何图像，检查下输入的tags")
            return
        else:
            print(f"找到 {count} 张图片")
            print(f"指定下载 {max_images_number} 张, 将执行 { download_count } 轮下载")
            print(f"下载将在 {wait_time} 秒后开始")

        # 下载前读秒
        for t in range(wait_time) :
            print(wait_time-t)
            await asyncio.sleep(1)
            
        
        class DownloadInfoCounter(object):
            """用于下载计数的类"""
            def __init__(self):
                """ 初始化所有计数为0 """
                self.all = 0
                self.success = 0
                self.duplicate = 0
                self.error = 0
            def update(self, download_info_tuple: tuple):
                """
                输入一个四长度的元组，按顺序复制给
                    全部任务、成功、重复、失败

                无返回值
                """
                if download_info_tuple:
                    self.all += download_info_tuple[0]
                    self.success += download_info_tuple[1]
                    self.duplicate += download_info_tuple[2]
                    self.error += download_info_tuple[3]
            def print(self):
                """按顺序输出相关信息"""
                print("*#" * 20)
                print("下载总结")
                print(f"下载任务： {self.all} 个")
                print(f"成功完成： {self.success} 个")
                print(f"存在重复： {self.duplicate} 个")
                print(f"下载失败： {self.error} 个")
        
        # 下载计数器
        download_info_counter = DownloadInfoCounter()
        
        # 实例化GetAPI类用于查询API获取pandas.df， 提供先前的async_client， 将在此函数执行完后才关闭
        get_api = GetAPI(base_url=base_url, base_url_params=base_url_params, async_client=async_client)

        # 创建下载文件夹
        await aiofiles.os.makedirs(download_dir, exist_ok=True)

        for i in range(download_count) :
            # print下载轮次
            divide_str = "#" * 20  # 显示每轮之间的分割字符
            tqdm.write(f"{divide_str}\n第 {i+1} / {download_count} 轮下载进行中:")

            # 查询API
            files_df = await get_api.get_api(tags, limit=limit, pid=i)
            
            if files_df is not None:

                def process_tags(tags: str,
                                add_comma: bool=True,
                                remove_underscore: bool=True,
                                use_escape: bool=True,
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
                
                files_df["tags"] = files_df["tags"].apply(process_tags,
                                                          add_comma=add_comma,
                                                          remove_underscore=remove_underscore,
                                                          use_escape=use_escape,
                                                    )

                res = await launch_executor(files_df, download_dir, max_workers=max_workers, timeout=timeout, async_client=async_client)
                download_info_counter.update( res )
            else:
                tqdm.write("第 {i+1} 轮下载失败")
            await asyncio.sleep(0.5)  # 休息一下，减轻压力
        
        download_info_counter.print()


        if check_images_mode not in [0, 1, 2, None]:
            logging.warning("check_images_mode 参数错误，其值将被置为None，且不进行检查")
            check_images_mode = None
        # 是否删除下载失败的图片
        if check_images_mode is not None:
            delete_list = await asyncio.to_thread(check_images, download_dir, max_workers=None, mode=check_images_mode, debug=True)


##############################
# 命令行脚本
if __name__ == "__main__":
    
    """ 用命令行读取参数并启动下载协程 """
    
    parser = argparse.ArgumentParser()

    parser.add_argument("--tags", type=str, default="girl", help="符合gelbooru规则的tags字符串")
    parser.add_argument("--max_images_number", type=int, default="50", help="下载图片数量")
    parser.add_argument("--download_dir", type=str, default=os.path.join(os.getcwd(),"images"), help="下载路径")
    parser.add_argument("--max_workers", type=int, default=15, help="最大协程工作数")
    parser.add_argument("--unit", type=int, default=50, help="下载单位，图片数量以此向上取一单位")
    parser.add_argument("--timeout", type=int, default=10, help="连接超时限制")
    parser.add_argument("--add_comma", action="store_true", help="是否在tags之间添加逗号")
    parser.add_argument("--remove_underscore", action="store_true", help="是否将tags中的下划线替换为空格")
    parser.add_argument("--use_escape", action="store_true", help="是否转义正则表达式特殊字符")
    parser.add_argument("--check_images_mode", type=int, default=None, help="None为不检查，0表示只检查并输出信息而不做任何操作，1表示检查并尝试修复图片，2表示检查并删除无法读取的图片")

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
    
    Scrape_images_coroutine = Scrape_images(tags,
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
    
    asyncio.run( Scrape_images_coroutine )
