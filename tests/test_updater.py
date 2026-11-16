import hashlib,io,json,tempfile,unittest
from pathlib import Path
from label_parser import updater

ASSETS=[
    {'name':'LabelDesk-0.8.0-Windows-x64-Setup.exe','browser_download_url':'https://example.test/setup.exe','size':200},
    {'name':'LabelDesk-0.8.0-Windows-x64-Portable.zip','browser_download_url':'https://example.test/portable.zip','size':456},
    {'name':'LabelDesk-0.8.0-macOS-AppleSilicon.dmg','browser_download_url':'https://example.test/mac.dmg','size':789},
]
PAYLOAD={'tag_name':'v0.8.0','body':'修复若干问题','html_url':'https://example.test/release','assets':ASSETS}

class Response(io.BytesIO):
    def __init__(self,data,headers=None):
        super().__init__(data);self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()

class UpdaterTest(unittest.TestCase):
    def test_version_comparison(self):
        self.assertTrue(updater.is_newer('v0.8.0','0.7.0'))
        self.assertTrue(updater.is_newer('0.7.1','0.7.0'))
        self.assertTrue(updater.is_newer('0.10.0','0.9.9'))
        self.assertFalse(updater.is_newer('0.7.0','0.7.0'))
        self.assertFalse(updater.is_newer('v0.7.0','0.7.0'))
        self.assertFalse(updater.is_newer('0.6.9','0.7.0'))

    def test_rejects_unknown_versions(self):
        for value in ['latest','',None,'v']:
            with self.assertRaises(updater.UpdateError):updater.version_key(value)

    def test_selects_asset_per_platform(self):
        self.assertEqual(updater.select_asset(ASSETS,'win32')['name'],'LabelDesk-0.8.0-Windows-x64-Setup.exe')
        self.assertEqual(updater.select_asset(ASSETS,'darwin')['name'],'LabelDesk-0.8.0-macOS-AppleSilicon.dmg')

    def test_rejects_unsupported_platform_and_missing_asset(self):
        with self.assertRaises(updater.UpdateError):updater.select_asset(ASSETS,'linux')
        with self.assertRaises(updater.UpdateError):updater.parse_release(dict(PAYLOAD,assets=[ASSETS[0]]),'darwin')

    def test_parse_release(self):
        release=updater.parse_release(PAYLOAD,'win32')
        self.assertEqual(release.version,'0.8.0')
        self.assertEqual(release.notes,'修复若干问题')
        self.assertEqual(release.asset_name,'LabelDesk-0.8.0-Windows-x64-Setup.exe')
        self.assertEqual(release.asset_url,'https://example.test/setup.exe')
        self.assertEqual(release.asset_size,200)
        self.assertEqual(release.page_url,'https://example.test/release')

    def test_fetch_latest_accepts_injected_reader(self):
        release=updater.fetch_latest('darwin',reader=lambda url:json.dumps(PAYLOAD).encode('utf-8'))
        self.assertEqual(release.asset_name,'LabelDesk-0.8.0-macOS-AppleSilicon.dmg')

    def test_download_writes_file_and_reports_progress(self):
        release=updater.parse_release(PAYLOAD,'win32');seen=[]
        with tempfile.TemporaryDirectory() as tmp:
            path=updater.download(release,tmp,progress=seen.append,opener=lambda url:Response(b'x'*200,{'Content-Length':'200'}))
            self.assertEqual(path,Path(tmp)/release.asset_name)
            self.assertEqual(path.read_bytes(),b'x'*200)
            self.assertEqual(seen[-1],1.0)
            self.assertFalse(Path(str(path)+'.part').exists())

    def test_download_verifies_sha256_digest(self):
        data=b'x'*200
        asset=dict(ASSETS[0],digest='sha256:'+hashlib.sha256(data).hexdigest())
        release=updater.parse_release(dict(PAYLOAD,assets=[asset]),'win32')
        with tempfile.TemporaryDirectory() as tmp:
            path=updater.download(release,tmp,opener=lambda url:Response(data,{'Content-Length':'200'}))
            self.assertEqual(path.read_bytes(),data)
            self.assertEqual(release.asset_digest,'sha256:'+hashlib.sha256(data).hexdigest())

    def test_download_rejects_sha256_mismatch(self):
        data=b'x'*200
        asset=dict(ASSETS[0],digest='sha256:'+'0'*64)
        release=updater.parse_release(dict(PAYLOAD,assets=[asset]),'win32')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(updater.UpdateError,'SHA-256'):
                updater.download(release,tmp,opener=lambda url:Response(data,{'Content-Length':'200'}))
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_download_rejects_truncated_file(self):
        release=updater.parse_release(PAYLOAD,'win32')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(updater.UpdateError):
                updater.download(release,tmp,opener=lambda url:Response(b'x'*10,{'Content-Length':'10'}))
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_download_wraps_network_errors(self):
        release=updater.parse_release(PAYLOAD,'win32')
        def broken(url):raise OSError('offline')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(updater.UpdateError):updater.download(release,tmp,opener=broken)

if __name__=='__main__':unittest.main()
