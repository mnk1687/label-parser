"""Check the GitHub release feed for a newer build and install it in place.

Only the official release page is queried over HTTPS; the download uses the
standard library so frozen builds need no extra dependency or signing key.
"""
import hashlib,json,os,re,subprocess,sys,tempfile,urllib.error,urllib.request
from dataclasses import dataclass
from pathlib import Path
from . import __version__

REPO='mnk1687/label-parser'
LATEST_RELEASE=f'https://api.github.com/repos/{REPO}/releases/latest'
TIMEOUT=15


class UpdateError(RuntimeError):
    """A user-facing failure; the message is shown verbatim in the app."""


@dataclass(frozen=True)
class Release:
    version:str
    notes:str
    asset_name:str
    asset_url:str
    asset_size:int
    page_url:str
    asset_digest:str=''


def version_key(text):
    """Turn 'v0.8.0' into (0, 8, 0); prerelease suffixes are ignored."""
    match=re.fullmatch(r'[vV]?(\d+(?:\.\d+)*)(?:[-+][0-9A-Za-z.-]+)?',str(text).strip())
    if not match:raise UpdateError(f'无法识别的版本号：{text}')
    return tuple(int(part) for part in match.group(1).split('.'))


def is_newer(candidate,current=__version__):
    newer,installed=version_key(candidate),version_key(current)
    size=max(len(newer),len(installed))
    return newer+(0,)*(size-len(newer))>installed+(0,)*(size-len(installed))


def select_asset(assets,platform_name=None):
    platform_name=(platform_name or sys.platform).lower()
    if platform_name.startswith('win'):
        wants=lambda name:'windows' in name and name.endswith('setup.exe')
    elif platform_name=='darwin':
        wants=lambda name:'macos' in name and name.endswith('.dmg')
    else:raise UpdateError('当前系统不支持应用内自动升级，请手动下载安装包。')
    for asset in assets:
        name=str(asset.get('name') or '')
        if wants(name.lower()):return asset
    raise UpdateError('这个版本没有提供当前系统的安装包，请到 Release 页面手动下载。')


def parse_release(payload,platform_name=None):
    version=str(payload.get('tag_name') or '').strip()
    version_key(version)
    asset=select_asset(payload.get('assets') or [],platform_name)
    name=str(asset.get('name') or '');url=str(asset.get('browser_download_url') or '')
    if not name or not url:raise UpdateError('这个版本的安装包信息不完整，请到 Release 页面手动下载。')
    return Release(version.lstrip('vV'),str(payload.get('body') or '').strip(),name,url,
                   int(asset.get('size') or 0),str(payload.get('html_url') or ''),
                   str(asset.get('digest') or ''))


def _open(url):
    request=urllib.request.Request(url,headers={'User-Agent':f'LabelDesk/{__version__}','Accept':'application/vnd.github+json'})
    try:return urllib.request.urlopen(request,timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code==404:raise UpdateError('还没有发布过正式版本。') from e
        raise UpdateError(f'GitHub 返回错误（HTTP {e.code}），请稍后再试。') from e
    except (urllib.error.URLError,OSError) as e:
        raise UpdateError(f'无法连接 GitHub：{getattr(e,"reason",e)}') from e


def _read(url):
    with _open(url) as response:return response.read()


def fetch_latest(platform_name=None,reader=None):
    reader=reader or _read
    raw=reader(LATEST_RELEASE)
    try:payload=json.loads(raw.decode('utf-8') if isinstance(raw,bytes) else raw)
    except (ValueError,AttributeError,UnicodeDecodeError) as e:raise UpdateError('GitHub 返回的数据无法解析。') from e
    return parse_release(payload,platform_name)


def download_folder():
    downloads=Path.home()/'Downloads'
    return downloads if downloads.is_dir() else Path(tempfile.gettempdir())


def expected_sha256(digest):
    """Accept GitHub's 'sha256:<hex>' asset digest; ignore anything else."""
    algorithm,_,value=str(digest or '').strip().lower().partition(':')
    return value if algorithm=='sha256' and len(value)==64 else ''


def download(release,folder=None,progress=None,opener=None):
    folder=Path(folder or download_folder());folder.mkdir(parents=True,exist_ok=True)
    opener=opener or _open
    destination=folder/release.asset_name;partial=folder/(release.asset_name+'.part')
    total=release.asset_size;done=0;hasher=hashlib.sha256()
    try:
        with opener(release.asset_url) as response:
            header=getattr(response,'headers',None) or {}
            total=total or int(header.get('Content-Length') or 0)
            with partial.open('wb') as handle:
                while True:
                    chunk=response.read(1<<16)
                    if not chunk:break
                    handle.write(chunk);hasher.update(chunk);done+=len(chunk)
                    if progress and total:progress(min(done/total,0.999))
        if total and done!=total:raise UpdateError(f'下载不完整（{done}/{total} 字节），请重试。')
        expected=expected_sha256(release.asset_digest)
        if expected and hasher.hexdigest()!=expected:
            raise UpdateError('安装包校验失败（SHA-256 不匹配），已删除下载文件，请重试。')
    except UpdateError:
        partial.unlink(missing_ok=True);raise
    except (OSError,urllib.error.URLError) as e:
        partial.unlink(missing_ok=True);raise UpdateError(f'下载安装包失败：{e}') from e
    os.replace(partial,destination)
    if progress:progress(1.0)
    return destination


def install(path):
    """Start the platform installer. The caller quits the app afterwards."""
    path=Path(path)
    if not path.is_file():raise UpdateError(f'安装包不存在：{path}')
    if sys.platform=='win32':
        subprocess.Popen([str(path)],close_fds=True);return
    if sys.platform=='darwin':
        _install_macos(path);return
    raise UpdateError('当前系统请手动打开安装包升级。')


def _install_macos(dmg):
    if not getattr(sys,'frozen',False):raise UpdateError('源码运行时不能自动替换应用，请手动打开安装包。')
    bundle=Path(sys.executable).resolve().parents[2]
    if bundle.suffix!='.app':raise UpdateError('找不到已安装的 LabelDesk.app，请手动打开安装包。')
    mount=Path(tempfile.mkdtemp(prefix='LabelDesk-dmg-'))
    attached=False
    try:
        result=subprocess.run(['hdiutil','attach',str(dmg),'-nobrowse','-readonly','-mountpoint',str(mount)],capture_output=True,text=True)
        if result.returncode!=0:raise UpdateError('无法打开下载的 dmg：'+result.stderr.strip())
        attached=True
        source=next((item for item in mount.iterdir() if item.name=='LabelDesk.app'),None)
        if source is None:raise UpdateError('dmg 中没有找到 LabelDesk.app。')
        copied=subprocess.run(['ditto','--norsrc','--noextattr',str(source),str(bundle)],capture_output=True,text=True)
        if copied.returncode!=0:raise UpdateError('替换应用失败，请手动拖入“应用程序”完成升级：'+copied.stderr.strip())
    finally:
        if attached:subprocess.run(['hdiutil','detach',str(mount),'-force'],capture_output=True)
