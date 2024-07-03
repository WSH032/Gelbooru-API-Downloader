"""用于检查图片是否存在问题，并可以修复被截断地图片."""

import argparse
import concurrent.futures
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Tuple, Union

from PIL import Image, ImageFile
from tqdm import tqdm

from utils._tools import search_img_files


def delete_files(
    files_list: List[str],
) -> Tuple[List[Tuple[str, Exception]], List[str]]:
    """删除文件列表中的所有文件.

    Args:
        files_list: 要删除的文件列表

    Returns:
        返回tuple(删除失败的文件路径和错误元组列表, 删除成功的文件路径列表)
    """
    failed_delete_files_list = []
    success_delete_files_list = []
    for f in files_list:
        try:
            os.remove(f)
            success_delete_files_list.append(f)
        except Exception as e:
            failed_delete_files_list.append((f, e))
            continue
    return failed_delete_files_list, success_delete_files_list


def _try_fix(image_path: str) -> Union[None, Tuple[str, Exception]]:
    """尝试修复图片，修复成功返回None，修复失败返回tuple(图片路径, 错误信息)"""
    try:
        with Image.open(image_path) as image:
            image.save(image_path)
            return None
    except Exception as e:
        return (image_path, e)


@contextmanager
def _allow_truncated_imgs_temporarily(is_allowed: bool) -> Generator[None]:
    """临时允许截断的图片"""
    ori_set = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = is_allowed
    yield
    ImageFile.LOAD_TRUNCATED_IMAGES = ori_set


def fix_images(
    images_list: List[str],
    max_workers: Union[int, None] = None,
) -> Tuple[List[Tuple[str, Exception]], List[str]]:
    """修复图片列表中的所有图片.

    Note: 这个函数不是线程安全的，会修改 `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` 的值.

    Args:
        images_list: 要修复的图片列表
        max_workers: 用于修复的并发线程数

    Returns:
        返回tuple(修复失败的文件路径和错误元组列表, 删除成功的文件路径列表)
    """
    # 应当考虑复用主线程中创建的线程池，而不是在这个函数中新建一个进程池，
    # 但是这样需要加更多逻辑，我有点懒得弄现在
    with _allow_truncated_imgs_temporarily(True), concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        futures_list = [
            executor.submit(_try_fix, image_path) for image_path in images_list
        ]

        # 获取结果
        failed_fix_images_list = []
        success_fix_images_list = []
        for future in concurrent.futures.as_completed(futures_list):
            result = future.result()
            if result is None:
                # 修复成功就记录该图片的路径
                success_fix_images_list.append(images_list[futures_list.index(future)])
            else:
                # 修复失败就记录tuple(图片绝对路径, 错误信息)
                failed_fix_images_list.append(result)

    return failed_fix_images_list, success_fix_images_list


def try_read(image_path: Path) -> Union[None, Tuple[str, Exception]]:
    """尝试读取图片.

    Args:
        image_path: 图片路径

    Returns:
        如果成功返回None，否则返回(图片名字, 错误信息).
        注意，返回的是不带路径的图片名字！
    """
    with Image.open(image_path) as image:
        try:
            image.load()
            return None
        except (OSError, SyntaxError) as e:
            return (os.path.basename(image_path), e)


def check_images(  # noqa: C901, PLR0912
    images_dir: str,
    mode: int = 0,
    debug: bool = False,
    max_workers: Union[int, None] = None,
) -> Tuple[List[Tuple[str, Exception]], List[str]]:
    """检查时候能正确读取images_dir目录下的图片

    iamges_dir: 要检查的目录
    mode: 0表示只检查，1表示检查并尝试修复，2表示检查并删除无法读取的图片
    debug: 是否打印详细信息
    max_workers: 线程池最大线程数

    返回tuple(无法读取的图片路径和错误元组列表, 修复成功的图片路径列表)
    """
    with _allow_truncated_imgs_temporarily(
        False
    ), concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:  # 需要设置为False，否则无法检测到截断
        futures_list = [
            executor.submit(try_read, image_path)
            for image_path in search_img_files(Path(images_dir))
        ]

        # 获取结果
        error_image_files_list = []
        for future in tqdm(
            concurrent.futures.as_completed(futures_list),
            total=len(futures_list),
            desc="检查图片中",
        ):
            result = future.result()
            if result is not None:
                error_image_files_list.append(result)

    print(
        f"检查了{len(futures_list)}张图片，其中{len(error_image_files_list)}张无法读取"
    )

    abs_path_error_list = [
        (os.path.join(images_dir, name), e) for name, e in error_image_files_list
    ]

    if mode == 0:
        if debug:
            for abs_path, e in abs_path_error_list:
                # 显示详细信息
                print(f"{abs_path} 无法读取, error: {e}")
        return abs_path_error_list, []

    elif mode == 1:
        # 尝试修复错误图片
        images_abs_path_list = [abs_path for abs_path, e in abs_path_error_list]
        failed_fix_images_list, success_fix_images_list = fix_images(
            images_abs_path_list, max_workers=max_workers
        )

        if debug:
            for abs_path in success_fix_images_list:
                print(f"{abs_path} 修复成功")
            for abs_path, e in failed_fix_images_list:
                print(f"{abs_path} 修复失败, error: {e}")
        print(
            f"尝试修复图片共{len(images_abs_path_list)}张，成功修复{len(success_fix_images_list)}张，修复失败{len(failed_fix_images_list)}张"
        )

        return failed_fix_images_list, success_fix_images_list

    elif mode == 2:
        # 尝试删除错误图片
        images_abs_path_list = [
            os.path.join(images_dir, name) for name, e in error_image_files_list
        ]
        failed_delete_images_list, success_delete_images_list = delete_files(
            images_abs_path_list
        )

        if debug:
            for abs_path in success_delete_images_list:
                print(f"{abs_path} 删除成功")
            for abs_path, e in failed_delete_images_list:
                print(f"{abs_path} 删除失败, error: {e}")
        print(
            f"尝试删除图片共{len(images_abs_path_list)}张，成功删除{len(success_delete_images_list)}张，删除失败{len(failed_delete_images_list)}张"
        )

        return failed_delete_images_list, success_delete_images_list

    else:
        raise ValueError("mode参数非法，只能为0,1,2中的一个")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("images_dir", type=str, help="要检查的目录")
    parser.add_argument(
        "--mode",
        type=int,
        default=0,
        help="0表示只检查而不做任何操作，1表示检查并尝试修复，2表示检查并删除无法读取的图片",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="是否打印详细信息，在控制台运行时且mode=0情况下建议开启",
    )
    parser.add_argument("--max_workers", type=int, default=None, help="处理线程数")

    cmd_param, unknown = parser.parse_known_args()
    if unknown:
        logging.warning(f"以下输入参数非法，将被忽略：\n{unknown}")

    check_images(**vars(cmd_param))
