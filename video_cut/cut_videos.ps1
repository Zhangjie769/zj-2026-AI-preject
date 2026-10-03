<#
.SYNOPSIS
  批量裁切视频脚本 —— 把目录下所有视频统一截取前 N 分钟并重新编码（精确刀口）。
.DESCRIPTION
  遍历源目录下所有指定扩展名的视频文件，每个裁剪为从头开始的指定时长（默认 40 分钟）。
  使用 libx264 重新编码，保证帧级精确裁剪，并保留字幕（若有）。输出到独立的输出目录，不会覆盖原文件。
   备注：裁剪秒数在脚本顶部用醒目的全局变量 $CUT_SECONDS 设置（默认 2400 秒 = 40 分钟），直接改那个数字即可。
.PARAMETER SourceDir
  源视频所在目录。默认取脚本所在目录。
.PARAMETER OutputDir
  输出目录。默认: <SourceDir>\_cut_<分钟数>s
.PARAMETER Extensions
  要处理的扩展名列表，默认 @('.mp4','.mkv','.avi','.mov','.ts','.flv','.wmv','.webm','.m4v','.mpg','.mpeg')
.PARAMETER ExtraArgs
  传给 ffmpeg 的额外参数（字符串）。默认使用编码参数。
.PARAMETER FfmpegPath
  ffmpeg 可执行文件路径。默认 'ffmpeg'（要求已在 PATH 中）。
.EXAMPLE
  ./cut_videos.ps1 -SourceDir "D:\videos"
  把 D:\videos 下所有视频各裁成前 $CUT_SECONDS 秒（脚本顶部改）。
.EXAMPLE
  ./cut_videos.ps1 -SourceDir "D:\videos" -OutputDir "D:\out"
  裁完后输出到 D:\out。
#>
param(
    [string]$SourceDir  = $PSScriptRoot,
    [string]$OutputDir  = "",
    [string[]]$Extensions = @('.mp4','.mkv','.avi','.mov','.ts','.flv','.wmv','.webm','.m4v','.mpg','.mpeg'),
    [string]$ExtraArgs  = "-c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 192k -movflags +faststart",
    [string]$FfmpegPath = "ffmpeg"
)

# =====================================================================
#    ★★★  你要改的核心参数：裁剪长度  ★★★
#   直接改下面这个数字，单位是【秒】。
#   例：想裁 40 分钟就填 2400；想裁 30 分钟就填 1800。
# =====================================================================
$CUT_SECONDS = 2400                   # <===== 在这里填秒数（40分钟 = 2400秒）====>
# =====================================================================

# 脚本内部统一用秒，直接用上面的变量即可
$Duration = $CUT_SECONDS

$ErrorActionPreference = 'Stop'

# ---------- 检查 ffmpeg ----------
$ffmpeg = Get-Command $FfmpegPath -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Write-Error "未找到 ffmpeg。请先安装并加入 PATH，或用 -FfmpegPath 指定完整路径。"
}
else {
    Write-Host "使用 ffmpeg: $($ffmpeg.Source)" -ForegroundColor Cyan
}

# ---------- 源目录检查 ----------
if (-not (Test-Path $SourceDir)) {
    Write-Error "源目录不存在: $SourceDir"
}
$SourceDir = (Resolve-Path $SourceDir).Path

# ---------- 输出目录 ----------
if ([string]::IsNullOrEmpty($OutputDir)) {
    $OutputDir = Join-Path $SourceDir "_cut_${Duration}s"
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}
$OutputDir = (Resolve-Path $OutputDir).Path

# ---------- 收集视频文件 ----------
$files = Get-ChildItem -File -Path $SourceDir | Where-Object {
    $_.Extension -and $Extensions -contains $_.Extension.ToLower()
} | Sort-Object Name

if ($files.Count -eq 0) {
    Write-Warning "在 '$SourceDir' 中没有找到扩展名为 $($Extensions -join ', ') 的视频文件。"
    exit 0
}

Write-Host ""
Write-Host "共找到 $($files.Count) 个视频，将各自截取前 $Duration 秒（$([math]::Round($Duration/60,2)) 分钟）。" -ForegroundColor Yellow
Write-Host "输出目录: $OutputDir" -ForegroundColor Yellow
Write-Host ""

$files.foreach({ Write-Host ("  - " + $_.Name) -ForegroundColor Gray })

# 备份用：每次换行的显示 + 失败记录
$failed = @()
$ok = 0

Write-Host ""
foreach ($f in $files) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
    $outFile = Join-Path $OutputDir ($base + "_cut${Duration}s" + ".mp4")

    Write-Host ("处理: " + $f.Name) -ForegroundColor Cyan

    # ffmpeg 参数。
    #   -y                  覆盖现有输出
    #   -i <input>          输入（-ss 放在 -i 之前，先快速定位关键帧起点；从 0 起所以只需 -t）
    #   -t <Duration>       截取时长
    #   -map 0:v:0          保留第一条视频流
    #   -map 0:a?           保留音频（没有就跳过）
    #   -map 0:s?           保留字幕流（没有就跳过）
    #   -c:v / -c:a         视频音频重编码；-c:s mov_text 把字幕转成 MP4 兼容格式以保留
    $mapArgs = @('-map','0:v:0','-map','0:a?','-map','0:s?')

    # 用户自定义编码参数（可覆盖默认的 -c:v -c:a -c:s 等）
    if (-not [string]::IsNullOrWhiteSpace($ExtraArgs)) {
        $extra = $ExtraArgs -split '\s+' | Where-Object { $_ -ne '' }
    } else {
        $extra = @()
    }

    # 组装完整参数：字幕默认用 mov_text（MP4 兼容），若用户没给 -c:s 才追加
    $hasSubCodec = $extra -contains '-c:s' -or $extra -contains '-c:s:0'
    if (-not $hasSubCodec) {
        $extra += @('-c:s','mov_text')
    }

    # 组装完整命令参数（逐行追加，避免行尾反引号续行出错）
    $ffargs = @('-y','-i',[string]$f.FullName,'-t',[string]$Duration)
    $ffargs += $mapArgs
    $ffargs += $extra
    $ffargs += @([string]$outFile)

    Write-Host ("  输出: " + $outFile)

    & $FfmpegPath @ffargs 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("  [失败] " + $f.Name + " ，退出码 " + $LASTEXITCODE) -ForegroundColor Red
        $failed += $f.Name
    }
    else {
        $ok++
        Write-Host ("  [完成] " + $f.Name) -ForegroundColor Green
    }
    Write-Host ""
}

# ---------- 汇总 ----------
Write-Host "=================== 完成 ===================" -ForegroundColor Cyan
Write-Host ("成功: $ok / $($files.Count)")
if ($failed.Count -gt 0) {
    Write-Host ("失败: $($failed.Count)") -ForegroundColor Red
    $failed.foreach({ Write-Host ("  - " + $_) -ForegroundColor Red })
}
Write-Host "输出目录: $OutputDir" -ForegroundColor Cyan