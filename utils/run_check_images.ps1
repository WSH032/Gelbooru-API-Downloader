$images_dir = "images"    # 要检查的目录 | the folder path to check images
$debug = 1    # 是否打印处理信息，$mode等于0时将强制开启 | whether to print debug info, will be forced to open when $mode is 0
$max_workers = 10    # 处理线程数 | number of threads to process

# 处理模式，0只展示错误信息，1会修复图片保留未阶段部分，2会删除错误图片 |
# mode for processing, 0 for only showing error messages, 1 for trying to fix images, 2 for deleting error images
$mode = 0


##########  检查脚本 do not edit  ##########
..\venv\Scripts\activate

$ext_args = [System.Collections.ArrayList]::new()

if ($debug -or $mode -eq 0) {
  [void]$ext_args.Add("--debug")
}

python check_images.py `
  $images_dir `
  --mode=$mode `
  --max_workers=$max_workers `
  $ext_args
  
pause
