import asyncio
import inspect
from typing import Coroutine, Tuple, Union


def create_task_index(*args, index: Union[int, None] = None, **kwargs) -> asyncio.Task:
    """在3.9<= python <=3.11中编写
    与asyncio.create_task具有相同的接口,以及行为
    但是增加了一个index参数，用于标记协程对象的索引

    index是关键词参数，如果不输入index，则保持和asyncio.create_task一样的行为
    如果输入了index，则会在asyncio.create_task的基础上，将输入协程对象替换为包装后的协程对象
    包装后的协程对象将会返回  Tuple[原协程对象的返回结果, index]
    """

    async def make_coro_index(coro: Coroutine, index: Union[int, None] = None):
        """包装协程对象，为协程对象的返回结果增加一个可选择的索引

        返回一个元组
        第一个元素为原协程对象的返回结果，第二个元素为index
        """
        return await coro, index

    def change_coro_in_args(args, index) -> Tuple:
        """将参数中的协程对象替换为包装后的协程对象"""
        args = list(args)
        # 找到协程对象在参数中的位置
        for i, arg in enumerate(args):
            if inspect.iscoroutine(arg):
                break
        else:
            raise ValueError("There is no coroutine object in args")

        args[i] = make_coro_index(arg, index)
        args = tuple(args)
        return args

    # 如果没输入index，则保持和asyncio.create_task一样的行为
    # 如果输入了index，则将协程对象替换为包装后的协程对象
    if index is not None:
        args = change_coro_in_args(args, index)

    return asyncio.create_task(*args, **kwargs)
