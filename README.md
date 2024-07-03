# Gelbooru-API-Downloader

A async coroutine script for gelbooru API and download.  

一个采用异步协程，用于通过指定tags关键词访问[Gelbooru](https://gelbooru.com/)公共API，并下载图片的脚本。

对于[SD训练](https://github.com/kohya-ss/sd-scripts)很有用。

## 现在我们有什么？

输入你想要的tags关键词，自动查询Gelbooru的API，然后采用异步协程方式，并发下载图片，同时会把gelbooru上图片的详细tags一同保存
特点：

- Download automatically | 自动化下载
- Download images with tag | 下载图片和tags
- MD5, Say no to duplication | 重复文件md5校验
- Asyncio and coroutine, fast | 协程异步并发写入和下载
- httpx and aiofiles | 全部采用协程，不包含任何同步阻塞操作
- Save detailed gelbooru tags txt concurrently | 下载图片同时保存详细的gelbooru tags
- Get gelbooru tags without downloading duplicate images | 已经存在图片但无tags文本，会自动补全

### powershell一键运行

![use_in_powershell](./docs/use_in_powershell.png)

### 并发下载，（用jupyter演示）

![Scrape_images](./docs/Scrape_images.png)

### API查询

![GetAPI](./docs/GetAPI.png)

## Credit

**Attention! It's probably against [Gelbooru's TOS](https://gelbooru.com/tos.php)!**

`scrape_images` 以自动的方式，httpx默认的UA头访问gelbooru的公共API，然后并发地异步下载图片

**虽然我没找到gelbooru在这方面的限制，但这仍然可能违反了gelbooru的政策！**

**不要滥用这个脚本，不要大量下载gelbooru的图片，保证下载频率和最大协程数不要过高！**

**如果你觉得这个脚本有用，你应该感谢gelbooru的无私贡献
你可以以[捐赠或者购买商品的形式](https://buymyshit.moneygrubbingwhore.com/index.php?page=products&s=list)支持他们**

## 安装

**请保证 `python>=3.9`**

```shell
pip install -r requirements.txt
```

## 使用方式

> [!TIP]
>
> 中国用户访问gelbooru请自行使用系统代理.
>
> 或者通过 `$env:HTTPS_PROXY = http://127.0.0.1:7890` 的方式，以环境变量 `HTTPS_PROXY`指定代理服务器.

<!-- 此注释是为了避免markdown lint报错 -->

> [!TIP]
>
> 这里有一些关于Gelbooru的tags/API规则:
>
> - [API](https://gelbooru.com/index.php?page=wiki&s=view&id=18780)
> - [tags](https://gelbooru.com/index.php?page=wiki&s=&s=view&id=25921)
> - [cheatsheet](https://gelbooru.com/index.php?page=wiki&s=&s=view&id=26263)

### 脚本方式(推荐)

在windows环境中，修改 [run_download_images_coroutine.ps1](run_download_images_coroutine.ps1) 中内容，powershell运行即可。

```shell
$tags = "hifumi_(blue_archive)"    # 符合gelbooru搜索规则的tags | tags for gelbooru
$max_images_number = 200    # 需要下载的图片数 | the number of images you need to download
$download_dir = "images"    # 下载图片的路径 | the folder path to download images
$max_workers= 15    # 最大下载协程数 | maximum number of download coroutines
$unit = 100    # 下载单位，下载图片数以此向上取一单位 | unit for download. eg: max_images_number=11, unit=10, then you get 20
$timeout = 10    # 下载超时限制 | download connecting timeout limit
```

### API方式

请查看[download_images_coroutine.py](download_images_coroutine.py)

## Todo

- [ ] 增加更多booru支持
- [ ] ~~增加对pixiv的支持~~
- [ ] 增加是否覆盖tags文本选项

## Change History

### 04 Jul.2024 2024/07/04

- **使用 `pydantic` 代替 `pandas` 作为依赖项**
- 重构代码，采用Google规范的Docstring
- 移除被弃用的多线程下载器
- 使用 `ruff` 进行格式化和lint修复
- 微调部分函数签名

<details>

<summary>More History</summary>

### 18 Jun.2023 2023/06/18

- 增加了显示下载速度的功能
- 基础类`class Downloader`的`.download()`方法输出类型已更改，现在会输出一个`class DownloadResult`的实例
    - 因为实现了`__eq__`方法，所以仍然可以用`Downloader.download() == 1`等判断下载是否成功
    - 具体请看[download_images_coroutine.py](download_images_coroutine.py)中的`class DownloadResult`定义

### 08 Jun.2023 2023/06/08

**新增了pillow库的要求.**

- 增加检查下载目录中错误图片的功能[1#issue](https://github.com/WSH032/Gelbooru-API-Downloader/issues/1)
    - 下载时候的使用方法请看[run_download_images_coroutine.ps1](run_download_images_coroutine.ps1)
    - 你也做为单独的工具脚本使用，请看[utils/run_check_images.ps1](utils/run_check_images.ps1)
    - API方式

      ```python
      await Scrape_images(*arg,**kwargs,
      check_images_mode: Union[None, int]=None,  # 新增参数
      )
      # check_images_mode为是否在下载结束后检查图片是否正确
      #   默认为None，不检查
      #   0为检查，但只输出信息不做任何操作
      #   1为尝试修复图片
      #   2为尝试删除图片
      ```

</details>
