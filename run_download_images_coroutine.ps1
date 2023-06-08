$tags = "hifumi_(blue_archive)"    # 符合gelbooru搜索规则的tags | tags for gelbooru
$max_images_number = 200    # 需要下载的图片数 | the number of images you need to download
$download_dir = "images"    # 下载图片的路径 | the folder path to download images
$max_workers= 15    # 最大下载协程数 | maximum number of download coroutines
$unit = 100    # 下载单位，下载图片数以此向上取一单位 | unit for download. eg: max_images_number=11, unit=10, then you get 20
$timeout = 10    # 下载超时限制 | download connecting timeout limit

$add_comma = 1    # 是否用逗号分割tags | whether to use comma to split tags
$remove_underscore = 1    # 是否移除tags中的下划线 | whether to remove underscore in tags
$use_escape = 1    # 是否对括号进行转义 | whether to escape parentheses

# 是否进行图片检查，-1为不检查，0为检查但只展示错误信息，1为检查并修复图片，2为检查并删除错误图片 |
# whether to check images, -1 for not checking, 0 for only showing error messages, 1 for trying to fix images, 2 for deleting error images
$check_images_mode = -1


##########  你可以在这找到tags规则 some useful info for tags   ##########
<# 

  API  https://gelbooru.com/index.php?page=wiki&s=view&id=18780
  tags  https://gelbooru.com/index.php?page=wiki&s=&s=view&id=25921
  cheatsheet  https://gelbooru.com/index.php?page=wiki&s=&s=view&id=26263

#>
##########  下载脚本 do not edit  ##########
.\venv\Scripts\activate

$ext_args = [System.Collections.ArrayList]::new()

if ($add_comma) {
  [void]$ext_args.Add("--add_comma")
}
if ($remove_underscore) {
  [void]$ext_args.Add("--remove_underscore")
}
if ($use_escape) {
  [void]$ext_args.Add("--use_escape")
}
if ($check_images_mode -ge 0) {
  [void]$ext_args.Add("--check_images_mode=$check_images_mode")
}

python download_images_coroutine.py `
  --tags=$tags `
  --max_images_number=$max_images_number `
  --download_dir=$download_dir `
  --max_workers=$max_workers `
  --unit=$unit `
  --timeout=$timeout `
  $ext_args
  
pause
