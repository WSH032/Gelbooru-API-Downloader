"""Created on Sun May  7 17:48:40 2023

@author: WSH
"""

from pathlib import Path

__all__ = ("IMAGE_EXTENSION", "search_img_files")


IMAGE_EXTENSION = {
    ".apng",
    ".blp",
    ".bmp",
    ".bufr",
    ".bw",
    ".cur",
    ".dcx",
    ".dds",
    ".dib",
    ".emf",
    ".eps",
    ".fit",
    ".fits",
    ".flc",
    ".fli",
    ".fpx",
    ".ftc",
    ".ftu",
    ".gbr",
    ".gif",
    ".grib",
    ".h5",
    ".hdf",
    ".icb",
    ".icns",
    ".ico",
    ".iim",
    ".im",
    ".j2c",
    ".j2k",
    ".jfif",
    ".jp2",
    ".jpc",
    ".jpe",
    ".jpeg",
    ".jpf",
    ".jpg",
    ".jpx",
    ".mic",
    ".mpeg",
    ".mpg",
    ".mpo",
    ".msp",
    ".palm",
    ".pbm",
    ".pcd",
    ".pcx",
    ".pdf",
    ".pgm",
    ".png",
    ".pnm",
    ".ppm",
    ".ps",
    ".psd",
    ".pxr",
    ".ras",
    ".rgb",
    ".rgba",
    ".sgi",
    ".tga",
    ".tif",
    ".tiff",
    ".vda",
    ".vst",
    ".webp",
    ".wmf",
    ".xbm",
    ".xpm",
}


def search_img_files(search_dir: Path) -> list[Path]:
    """搜索目录下已注册的扩展名的所有图片."""

    def is_image_file(file: Path) -> bool:
        return file.suffix.lower() in IMAGE_EXTENSION and file.is_file()

    return list(filter(is_image_file, search_dir.iterdir()))
