import requests
import re
import json
import sys
import pickle
import os.path
import subprocess
from typing import Optional, Dict, Any, List

class PornHubScraper:

    def __init__(self, cookies_path: Optional[str] = None):
        self.cookies_path = cookies_path
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        self.proxies = {
            'http': None,
            'https': None,
        }
        self.age_cookies = {
            'age_verified': '1',
            'accessAgeDisclaimerPH': '1',
            'accessPH': '1',
        }
        
        self.video_regex = re.compile(
            r'https?://(?:[^/]+\.)?(pornhub(?:premium)?\.(?:com|net|org))/'
            r'.*(?:view_video\.php\?viewkey=|video/show\?viewkey=|embed/)(?P<id>[\da-z]+)',
            re.IGNORECASE
        )

        if self.cookies_path and os.path.isfile(self.cookies_path):
            self.load_cookies()

    def set_proxies(self, http_proxy: str, https_proxy: str) -> None:
        self.proxies['http'] = http_proxy
        self.proxies['https'] = https_proxy

    def load_cookies(self) -> bool:
        try:
            with open(self.cookies_path, 'rb') as f:
                cookies = pickle.load(f)
                self.session.cookies.update(cookies)
            return True
        except Exception as e:
            print(f"Error loading cookies: {e}")
            return False

    def set_age_cookies(self, host: str) -> None:
        for key, value in self.age_cookies.items():
            self.session.cookies.set(key, value, domain=host)

    def download_webpage(self, url: str) -> str:
        try:
            response = self.session.get(url, headers=self.headers, proxies=self.proxies, timeout=10)
            response.raise_for_status()
            webpage = response.text

            if any(keyword in webpage for keyword in ['onload="go(', 'document.cookie', 'location.reload']):
                host = re.search(r'https?://([^/]+)', url).group(1)
                self.set_age_cookies(host)
                response = self.session.get(url, headers=self.headers, proxies=self.proxies, timeout=10)
                response.raise_for_status()
                webpage = response.text

            return webpage
        except Exception as e:
            raise Exception(f'Error downloading page: {e}')

    def download_webpage_with_js(self, url: str) -> str:
        try:
            env = os.environ.copy()
            env['OPENSSL_CONF'] = '/etc/ssl/openssl-legacy.cnf'
            cmd = ['phantomjs', 'phantom_downloader.js', url]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
            return result.stdout
        except Exception as e:
            raise Exception(f'Error downloading page using PhantomJS: {e}')

    def extract_video_info(self, url: str) -> Dict[str, Any]:
        m = self.video_regex.match(url)
        if not m:
            raise Exception("The provided URL is not valid for PornHub.")
        host = m.group(1)
        video_id = m.group('id')

        webpage = self.download_webpage(url)

        error_search = re.search(
            r'<div[^>]+class=["\'](?:removed|userMessageSection)[^>]*>(?P<error>.+?)</div>',
            webpage, re.DOTALL
        )
        if error_search:
            error_msg = re.sub(r'\s+', ' ', error_search.group('error')).strip()
            raise Exception(f"PornHub reports an error: {error_msg}")

        title = f"DescargarBot_PornHub_{video_id}"

        flashvars_search = re.search(r'var\s+flashvars_\d+\s*=\s*(\{.+?\});', webpage, re.DOTALL)
        if not flashvars_search:
            print("Content appears to be dynamically generated. Using PhantomJS to obtain processed HTML...")
            webpage_js = self.download_webpage_with_js(url)
            flashvars_search = re.search(r'var\s+flashvars_\d+\s*=\s*(\{.+?\});', webpage_js, re.DOTALL)
            if flashvars_search:
                webpage = webpage_js

        flashvars_json = {}
        if flashvars_search:
            try:
                flashvars_json = json.loads(flashvars_search.group(1))
            except json.JSONDecodeError:
                flashvars_json = {}

        duration = flashvars_json.get('video_duration')
        thumbnail = flashvars_json.get('image_url')

        formats: List[Dict[str, Any]] = []
        media_definitions = flashvars_json.get('mediaDefinitions')
        if isinstance(media_definitions, list):
            seen_urls = set()
            for definition in media_definitions:
                if isinstance(definition, dict):
                    video_url = definition.get('videoUrl')
                    quality = definition.get('quality')
                    if video_url and video_url not in seen_urls:
                        seen_urls.add(video_url)
                        formats.append({
                            'url': video_url,
                            'format_id': f'{quality}p' if quality else None,
                            'quality': quality
                        })

        return {
            'id': video_id,
            'title': title,
            'duration': duration,
            'thumbnail': thumbnail,
            'formats': formats,
        }

    def get_best_format(self, formats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not formats:
            return None
        
        def get_quality_value(fmt):
            quality = fmt.get('quality')
            if quality is None:
                return 0
            if isinstance(quality, list):
                quality = quality[0] if quality else 0
            try:
                return int(quality)
            except (ValueError, TypeError):
                return 0
        
        best_format = max(formats, key=get_quality_value)
        return best_format

    def download_video_with_ffmpeg(self, m3u8_url: str, output_video: str) -> bool:
        try:
            cmd = [
                'ffmpeg',
                '-user_agent', self.headers['User-Agent'],
                '-i', m3u8_url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                output_video
            ]
            
            print("Downloading video with ffmpeg...")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"Video downloaded successfully: {output_video}")
            
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error executing ffmpeg: {e}")
            print(f"stderr: {e.stderr}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("You must provide a PornHub video URL")
        sys.exit(1)

    video_url = sys.argv[1]
    scraper = PornHubScraper()

    try:
        video_info = scraper.extract_video_info(video_url)
        print("Video information:")
        print(json.dumps(video_info, indent=4))
        
        best_format = scraper.get_best_format(video_info['formats'])
        if best_format:
            print(f"\nBest format found: {best_format['format_id']} - {best_format['url']}")
            
            output_video = f"{video_info['title']}.mp4"
            output_video = re.sub(r'[<>:"/\\|?*]', '_', output_video)
            scraper.download_video_with_ffmpeg(best_format['url'], output_video)
        else:
            print("No available formats found")
            
    except Exception as e:
        print(f"Error: {e}")
