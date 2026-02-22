import requests
import re
import json
import sys
import pickle
import os.path
import subprocess
from typing import Optional, Dict, Any, List


# ─────────────────────────────────────────────
#  NordVPN SOCKS5 helper
# ─────────────────────────────────────────────

def get_best_nordvpn_proxy(user: str, password: str) -> Dict[str, str]:
    """
    Consulta la API de NordVPN, elige el servidor SOCKS5 con menor carga
    y devuelve un dict de proxies listo para usar con requests.

    Países disponibles con SOCKS5: EE.UU., Países Bajos, Suecia.

    Args:
        user (str): Usuario de servicio NordVPN 
        password (str): Contraseña de servicio NordVPN.

    Returns:
        dict: Proxies configurados con el mejor servidor SOCKS5.

    Raises:
        Exception: Si no se puede obtener la lista de servidores o está vacía.
    """
    try:
        response = requests.get(
            "https://api.nordvpn.com/v1/servers",
            params={
                "filters[servers_technologies][identifier]": "socks",
                "limit": 100
            },
            timeout=10
        )
        response.raise_for_status()
        servers = response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error al consultar la API de NordVPN: {e}")

    if not servers:
        raise Exception("No se encontraron servidores SOCKS5 disponibles en NordVPN.")

    best = min(servers, key=lambda s: s.get("load", 999))
    host = best["hostname"]
    load = best.get("load", "?")
    print(f"[NordVPN] Mejor servidor SOCKS5: {host} - {load}% carga")

    proxy_url = f"socks5h://{user}:{password}@{host}:1080"
    return {"http": proxy_url, "https": proxy_url}


# ─────────────────────────────────────────────
#  Scraper
# ─────────────────────────────────────────────

class PornHubScraper:

    NORDVPN_USER = ""
    NORDVPN_PASS = ""

    def __init__(self, cookies_path: Optional[str] = None, use_nordvpn: bool = True):
        """
        Inicializa el scraper para PornHub.

        Args:
            cookies_path (str, opcional): Ruta al archivo de cookies (pickle).
            use_nordvpn (bool): Si True, configura automáticamente el proxy SOCKS5
                                de NordVPN eligiendo el servidor con menor carga.
        """
        self.cookies_path = cookies_path
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        self.proxies: Dict[str, Optional[str]] = {"http": None, "https": None}

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

        if use_nordvpn:
            if not self.NORDVPN_USER or not self.NORDVPN_PASS:
                print("[NordVPN] ADVERTENCIA: Credenciales no configuradas. Continuando sin proxy.")
            else:
                try:
                    self.proxies = get_best_nordvpn_proxy(self.NORDVPN_USER, self.NORDVPN_PASS)
                except Exception as e:
                    print(f"[NordVPN] No se pudo configurar el proxy: {e}. Continuando sin proxy.")

        if self.cookies_path and os.path.isfile(self.cookies_path):
            self.load_cookies()

    def set_proxies(self, http_proxy: str, https_proxy: str) -> None:
        """
        Permite sobreescribir manualmente los proxies HTTP y HTTPS.

        Args:
            http_proxy (str): Dirección del proxy HTTP.
            https_proxy (str): Dirección del proxy HTTPS.
        """
        self.proxies["http"] = http_proxy
        self.proxies["https"] = https_proxy

    def load_cookies(self) -> bool:
        """
        Carga las cookies almacenadas en el archivo especificado.

        Returns:
            bool: True si se cargaron correctamente, False en caso contrario.
        """
        try:
            with open(self.cookies_path, 'rb') as f:
                cookies = pickle.load(f)
                self.session.cookies.update(cookies)
            return True
        except Exception as e:
            print(f"[Cookies] Error al cargar las cookies: {e}")
            return False

    def set_age_cookies(self, host: str) -> None:
        """
        Establece las cookies para evitar la verificación de edad.

        Args:
            host (str): Dominio (ej: pornhub.com).
        """
        for key, value in self.age_cookies.items():
            self.session.cookies.set(key, value, domain=host)

    def _init_session(self, base_url: str = "https://www.pornhub.com") -> None:
        """
        Hace un request inicial a PornHub para establecer cookies de sesión anónima.
        Útil para evitar que el CDN devuelva URLs con f=1 (free preview).
        Llamar manualmente si se desea pre-calentar la sesión antes de extract_video_info.
        """
        try:
            response = self.session.get(
                base_url,
                headers=self.headers,
                proxies=self.proxies,
                timeout=15
            )
            host = re.search(r'https?://([^/]+)', response.url)
            if host:
                self.set_age_cookies(host.group(1))
            print(f"[Session] Sesión inicializada - {len(self.session.cookies)} cookies")
        except Exception as e:
            print(f"[Session] Warning: no se pudo inicializar la sesión: {e}")

    def download_webpage(self, url: str) -> str:
        """
        Descarga el HTML de una página. Si detecta verificación de edad,
        establece las cookies necesarias y reintenta.

        Args:
            url (str): URL a descargar.

        Returns:
            str: Contenido HTML.

        Raises:
            Exception: Si ocurre un error en la descarga.
        """
        try:
            response = self.session.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            response.raise_for_status()
            webpage = response.text

            if any(kw in webpage for kw in ['onload="go(', 'document.cookie', 'location.reload']):
                host_match = re.search(r'https?://([^/]+)', url)
                if host_match:
                    self.set_age_cookies(host_match.group(1))
                response = self.session.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
                response.raise_for_status()
                webpage = response.text

            return webpage

        except requests.exceptions.ProxyError as e:
            raise Exception(f"Error de proxy (verificá las credenciales NordVPN): {e}")
        except requests.exceptions.ConnectTimeout:
            raise Exception(f"Timeout al conectar con {url}. El servidor proxy puede estar caído.")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error al descargar la página: {e}")

    def download_webpage_with_js(self, url: str) -> str:
        """
        Descarga el HTML procesado mediante PhantomJS (para contenido generado dinámicamente).

        Args:
            url (str): URL a descargar.

        Returns:
            str: HTML procesado.

        Raises:
            Exception: Si ocurre un error al ejecutar PhantomJS.
        """
        try:
            env = os.environ.copy()
            env['OPENSSL_CONF'] = '/etc/ssl/openssl-legacy.cnf'
            cmd = ['phantomjs', 'phantom_downloader.js', url]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise Exception(f"Error al ejecutar PhantomJS: {e.stderr}")
        except FileNotFoundError:
            raise Exception("PhantomJS no está instalado o no se encuentra en el PATH.")
        except Exception as e:
            raise Exception(f"Error inesperado con PhantomJS: {e}")

    def _resolve_formats_from_get_media(self, get_media_url: str, referer: str) -> List[Dict[str, Any]]:
        """
        Llama al endpoint get_media y devuelve los formatos reales en MP4 directo.

        Este endpoint devuelve URLs del CDN ev.phncdn.com firmadas con la IP actual,
        sin restricción de preview (f=1). Se usa como fallback cuando los formatos
        de flashvars provienen del CDN hv-h.phncdn.com con f=1.

        Args:
            get_media_url (str): URL del endpoint get_media (extraída de flashvars).
            referer (str): URL del video, usada como Referer en el request.

        Returns:
            list: Lista de formatos con url, format_id, quality, width, height.
        """
        try:
            response = self.session.get(
                get_media_url,
                headers={**self.headers, 'Referer': referer},
                proxies=self.proxies,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, list):
                print(f"[get_media] Respuesta inesperada: {data}")
                return []

            formats = []
            for item in data:
                video_url = item.get('videoUrl')
                quality = item.get('quality')
                if video_url:
                    formats.append({
                        'url': video_url,
                        'format_id': f"{quality}p" if quality else None,
                        'quality': quality,
                        'width': item.get('width'),
                        'height': item.get('height'),
                    })

            print(f"[get_media] {len(formats)} formatos obtenidos desde ev.phncdn.com")
            return formats

        except requests.exceptions.RequestException as e:
            print(f"[get_media] Error de red: {e}")
            return []
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[get_media] Error al parsear respuesta: {e}")
            return []
        except Exception as e:
            print(f"[get_media] Error inesperado: {e}")
            return []

    def extract_video_info(self, url: str) -> Dict[str, Any]:
        """
        Extrae la información del video a partir de la URL de PornHub.

        Flujo:
        1. Descarga la página y parsea flashvars.
        2. Si los formatos tienen f=1 (CDN hv-h, sesión sin cookies),
           llama al endpoint get_media para obtener URLs directas MP4.
        3. Si get_media devuelve formatos válidos, los usa en lugar de los de flashvars.

        Args:
            url (str): URL del video en PornHub.

        Returns:
            dict: id, title, duration, thumbnail, formats.

        Raises:
            Exception: Si la URL no es válida o hay un error en la página.
        """
        # Sesión limpia por cada video para evitar contaminación entre requests
        self.session = requests.Session()

        m = self.video_regex.match(url)
        if not m:
            raise Exception("La URL proporcionada no es válida para PornHub.")
        video_id = m.group('id')

        webpage = self.download_webpage(url)

        error_search = re.search(
            r'<div[^>]+class=["\'](?:removed|userMessageSection)[^>]*>(?P<e>.+?)</div>',
            webpage, re.DOTALL
        )
        if error_search:
            error_msg = re.sub(r'\s+', ' ', error_search.group('e')).strip()
            raise Exception(f"PornHub reporta un error: {error_msg}")

        title = f"DescargarBot_PornHub_{video_id}"

        flashvars_search = re.search(r'var\s+flashvars_\d+\s*=\s*(\{.+?\});', webpage, re.DOTALL)
        if not flashvars_search:
            print("[Scraper] Contenido dinámico detectado. Usando PhantomJS...")
            try:
                webpage_js = self.download_webpage_with_js(url)
                flashvars_search = re.search(r'var\s+flashvars_\d+\s*=\s*(\{.+?\});', webpage_js, re.DOTALL)
                if flashvars_search:
                    webpage = webpage_js
            except Exception as e:
                print(f"[Scraper] PhantomJS falló: {e}")

        flashvars_json = {}
        if flashvars_search:
            try:
                flashvars_json = json.loads(flashvars_search.group(1))
            except json.JSONDecodeError as e:
                print(f"[Scraper] Error al parsear flashvars JSON: {e}")

        duration = flashvars_json.get('video_duration')
        thumbnail = flashvars_json.get('image_url')

        # Parsear formatos desde mediaDefinitions
        formats: List[Dict[str, Any]] = []
        get_media_url: Optional[str] = None
        media_definitions = flashvars_json.get('mediaDefinitions')

        if isinstance(media_definitions, list):
            seen_urls: set = set()
            for definition in media_definitions:
                if isinstance(definition, dict):
                    video_url = definition.get('videoUrl')
                    quality = definition.get('quality')
                    if not video_url or video_url in seen_urls:
                        continue
                    seen_urls.add(video_url)
                    # Detectar el endpoint get_media (sin calidad definida)
                    if 'get_media' in video_url:
                        get_media_url = video_url
                    else:
                        formats.append({
                            'url': video_url,
                            'format_id': f'{quality}p' if quality else None,
                            'quality': quality,
                        })

        # Si los formatos vienen del CDN limitado (hv-h con f=1), usar get_media como fallback
        has_preview_only = any(
            'hv-h.phncdn.com' in f.get('url', '') and '&f=1' in f.get('url', '')
            for f in formats
        )

        if has_preview_only and get_media_url:
            print("[Scraper] CDN hv-h detectado con f=1, resolviendo via get_media...")
            real_formats = self._resolve_formats_from_get_media(get_media_url, url)
            if real_formats:
                formats = real_formats

        return {
            'id': video_id,
            'title': title,
            'duration': duration,
            'thumbnail': thumbnail,
            'formats': formats,
        }

    def get_best_format(self, formats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Selecciona el formato de mayor calidad.

        Args:
            formats (list): Lista de formatos disponibles.

        Returns:
            dict: Formato con mayor calidad, o None si la lista está vacía.
        """
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

        return max(formats, key=get_quality_value)

    def _ffmpeg_header_string(self, extra: Optional[Dict[str, str]] = None) -> str:
        hdr = {"User-Agent": self.headers["User-Agent"]}
        cookies = "; ".join(f"{c.name}={c.value}" for c in self.session.cookies)
        if cookies:
            hdr["Cookie"] = cookies
        if extra:
            hdr.update(extra)
        return "".join(f"{k}: {v}\r\n" for k, v in hdr.items())

    def download_video_with_ffmpeg(self, video_url: str, output_video: str, referer_url: Optional[str] = None) -> bool:
        """
        Descarga el video usando ffmpeg. Soporta tanto URLs MP4 directas como m3u8.

        Args:
            video_url (str): URL del video (MP4 directo o m3u8).
            output_video (str): Ruta de salida del video.
            referer_url (str, opcional): URL de referencia para los headers.

        Returns:
            bool: True si fue exitoso, False en caso contrario.
        """
        try:
            header_str = self._ffmpeg_header_string({"Referer": referer_url} if referer_url else None)

            # Para MP4 directo no necesita -bsf:a aac_adtstoasc (solo para HLS)
            is_hls = 'm3u8' in video_url.lower()
            cmd = [
                'ffmpeg',
                '-user_agent', self.headers['User-Agent'],
                '-headers', header_str,
                '-i', video_url,
                '-c', 'copy',
            ]
            if is_hls:
                cmd += ['-bsf:a', 'aac_adtstoasc']
            cmd.append(output_video)

            print(f"[ffmpeg] Descargando {'HLS' if is_hls else 'MP4 directo'}...")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"[ffmpeg] Video guardado en: {output_video}")
            return True

        except subprocess.CalledProcessError as e:
            print(f"[ffmpeg] Error: {e.stderr[-500:] if e.stderr else e}")
            return False
        except FileNotFoundError:
            print("[ffmpeg] ffmpeg no está instalado o no se encuentra en el PATH.")
            return False
        except Exception as e:
            print(f"[ffmpeg] Error inesperado: {e}")
            return False


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python pornhub_scraper.py <URL_del_video>")
        sys.exit(1)

    video_url = sys.argv[1]

    try:
        # Usar use_nordvpn=False si no usas nordVPN
        scraper = PornHubScraper(use_nordvpn=True)
    except Exception as e:
        print(f"Error al inicializar el scraper: {e}")
        sys.exit(1)

    try:
        video_info = scraper.extract_video_info(video_url)
        print("\nInformación del video:")
        print(json.dumps(video_info, indent=4))

        best_format = scraper.get_best_format(video_info['formats'])
        if best_format:
            print(f"\nMejor formato: {best_format['format_id']} - {best_format['url']}")
            output_video = re.sub(r'[<>:"/\\|?*]', '_', f"{video_info['title']}.mp4")
            scraper.download_video_with_ffmpeg(best_format['url'], output_video, referer_url=video_url)
        else:
            print("No se encontraron formatos disponibles.")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
