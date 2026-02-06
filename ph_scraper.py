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
        """
        Inicializa el scraper para PornHub.
        Args:
            cookies_path (str, opcional): Ruta al archivo de cookies (pickle). Si se
                                        proporciona, se cargarán las cookies al iniciar.
        """
        self.cookies_path = cookies_path
        self.session = requests.Session()
        self.headers = {
            # Se recomienda utilizar un user-agent actualizado
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        self.proxies = {
            'http': None,
            'https': None,
        }
        # Cookies para saltar la verificación de edad
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

        # Si se proporcionó un archivo de cookies, se intenta cargar
        if self.cookies_path and os.path.isfile(self.cookies_path):
            self.load_cookies()

    def set_proxies(self, http_proxy: str, https_proxy: str) -> None:
        """
        Configura los proxies HTTP y HTTPS de la sesión.

        Args:
            http_proxy (str): Dirección del proxy HTTP.
            https_proxy (str): Dirección del proxy HTTPS.
        """
        self.proxies['http'] = http_proxy
        self.proxies['https'] = https_proxy

    def load_cookies(self) -> bool:
        """
        Carga las cookies almacenadas en el archivo especificado.

        Returns:
            bool: True si se cargaron las cookies, False si no existe el archivo.
        """
        try:
            with open(self.cookies_path, 'rb') as f:
                cookies = pickle.load(f)
                self.session.cookies.update(cookies)
            return True
        except Exception as e:
            print(f"Error al cargar las cookies: {e}")
            return False

    def set_age_cookies(self, host: str) -> None:
        """
        Establece las cookies necesarias para evitar la verificación de edad.

        Args:
            host (str): Dominio sobre el que se establecerán las cookies (ejemplo: pornhub.com).
        """
        for key, value in self.age_cookies.items():
            # Se asigna la cookie al dominio indicado
            self.session.cookies.set(key, value, domain=host)

    def download_webpage(self, url: str) -> str:
        """
        Descarga el contenido HTML de una página.

        Si se detecta algún patrón que indica redirección por JavaScript o verificación de edad,
        se establece la cookie correspondiente y se vuelve a descargar la página.

        Args:
            url (str): URL de la página a descargar.
        
        Returns:
            str: Contenido HTML de la página.
        
        Raises:
            Exception: En caso de error al descargar la página.
        """
        try:
            response = self.session.get(url, headers=self.headers, proxies=self.proxies, timeout=10)
            response.raise_for_status()
            webpage = response.text

            # Si se detecta contenido de verificación de edad o redirección por JS,
            # se establecen las cookies de "edad verificada" y se vuelve a solicitar la página.
            if any(keyword in webpage for keyword in ['onload="go(', 'document.cookie', 'location.reload']):
                host = re.search(r'https?://([^/]+)', url).group(1)
                self.set_age_cookies(host)
                response = self.session.get(url, headers=self.headers, proxies=self.proxies, timeout=10)
                response.raise_for_status()
                webpage = response.text

            return webpage
        except Exception as e:
            raise Exception(f'Error al descargar la página: {e}')

    def download_webpage_with_js(self, url: str) -> str:
        """
        Descarga el HTML procesado de una página mediante PhantomJS.

        Esta función se utiliza para obtener el contenido final cuando la página depende de
        JavaScript para renderizar parte de su información. Para ello se asume que PhantomJS
        está instalado y que se dispone de un script (por ejemplo, phantom_downloader.js) que
        recibe la URL como argumento y devuelve el HTML procesado.

        Args:
            url (str): URL de la página a descargar.
        
        Returns:
            str: HTML procesado obtenido mediante PhantomJS.
        
        Raises:
            Exception: En caso de error al ejecutar PhantomJS.
        """
        try:
            env = os.environ.copy()
            env['OPENSSL_CONF'] = '/etc/ssl/openssl-legacy.cnf'
            # Se asume que 'phantom_downloader.js' está en el mismo directorio y es ejecutable por PhantomJS.
            cmd = ['phantomjs', 'phantom_downloader.js', url]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
            return result.stdout
        except Exception as e:
            raise Exception(f'Error al descargar la página usando PhantomJS: {e}')

    def extract_video_info(self, url: str) -> Dict[str, Any]:
        """
        Extrae la información del video a partir de la URL de PornHub.

        Se descarga la página y se buscan mediante expresiones regulares parámetros como
        la ID, el título, la duración, el thumbnail y los formatos (calidades) disponibles.
        Si no se encuentran ciertos datos típicos (por ejemplo, el bloque de flashvars) se
        asume que el contenido puede ser generado dinámicamente, por lo que se intenta obtener
        el HTML ejecutando JavaScript con PhantomJS.

        Args:
            url (str): URL del video en PornHub.

        Returns:
            dict: Diccionario con la información del video (id, title, duration, thumbnail, formats).

        Raises:
            Exception: Si la URL no es válida o se detecta un error en la página.
        """
        m = self.video_regex.match(url)
        if not m:
            raise Exception("La URL proporcionada no es válida para PornHub.")
        host = m.group(1)
        video_id = m.group('id')

        # Descargar la página del video
        webpage = self.download_webpage(url)

        # Verificar si la página muestra un mensaje de error (video removido o privado)
        error_search = re.search(
            r'<div[^>]+class=["\'](?:removed|userMessageSection)[^>]*>(?P<error>.+?)</div>',
            webpage, re.DOTALL
        )
        if error_search:
            error_msg = re.sub(r'\s+', ' ', error_search.group('error')).strip()
            raise Exception(f"PornHub reporta un error: {error_msg}")

        title = f"DescargarBot_PornHub_{video_id}"

        # Intentar extraer el JSON de flashvars (ejemplo: var flashvars_123456 = {...};)
        flashvars_search = re.search(r'var\s+flashvars_\d+\s*=\s*(\{.+?\});', webpage, re.DOTALL)
        # Si no se encuentra, es posible que el contenido se genere dinámicamente.
        if not flashvars_search:
            print("El contenido parece estar generado dinámicamente. Usando PhantomJS para obtener el HTML procesado...")
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

        # Extraer algunos parámetros opcionales: duración y thumbnail
        duration = flashvars_json.get('video_duration')
        thumbnail = flashvars_json.get('image_url')

        # Extraer los formatos desde "mediaDefinitions".
        # Se recorre la lista de definiciones y se obtiene el videoUrl y la calidad.
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
        """
        Selecciona el mejor formato disponible (mayor calidad).

        Args:
            formats (list): Lista de formatos extraídos del video.

        Returns:
            dict: El formato con la mayor calidad, o None si no hay formatos.
        """
        if not formats:
            return None
        
        def get_quality_value(fmt):
            """Extrae el valor numérico de calidad."""
            quality = fmt.get('quality')
            if quality is None:
                return 0
            # Si es una lista, tomar el primer elemento
            if isinstance(quality, list):
                quality = quality[0] if quality else 0
            # Intentar convertir a int
            try:
                return int(quality)
            except (ValueError, TypeError):
                return 0
        
        # Ordenar por calidad (de mayor a menor) y retornar el primero
        best_format = max(formats, key=get_quality_value)
        return best_format

    def _ffmpeg_header_string(self, extra: Optional[Dict[str, str]] = None) -> str:
        hdr = {"User-Agent": self.headers["User-Agent"]}
        cookies = "; ".join(f"{c.name}={c.value}" for c in self.session.cookies)
        if cookies:
            hdr["Cookie"] = cookies
        if extra:
            hdr.update(extra)
        return "".join(f"{k}: {v}\r\n" for k, v in hdr.items())

    def download_video_with_ffmpeg(self, m3u8_url: str, output_video: str, referer_url: Optional[str] = None) -> bool:
        """
        Descarga el video usando ffmpeg a partir de la URL m3u8.

        Args:
            m3u8_url (str): URL del archivo m3u8.
            output_video (str): Ruta donde se guardará el video final.

        Returns:
            bool: True si la descarga fue exitosa, False en caso contrario.
        """
        try:
            header_str = self._ffmpeg_header_string({"Referer": referer_url} if referer_url else None)
            # Comando de ffmpeg con el user-agent usando directamente la URL
            cmd = [
                'ffmpeg',
                '-user_agent', self.headers['User-Agent'],
                '-headers', header_str,
                '-i', m3u8_url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                output_video
            ]
            
            print("Descargando video con ffmpeg...")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"Video descargado exitosamente: {output_video}")
            
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error al ejecutar ffmpeg: {e}")
            print(f"stderr: {e.stderr}")
            return False
        except Exception as e:
            print(f"Error inesperado: {e}")
            return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Debe proporcionar la URL de un video de PornHub")
        sys.exit(1)

    video_url = sys.argv[1]
    scraper = PornHubScraper()

    try:
        # Extraer información del video
        video_info = scraper.extract_video_info(video_url)
        print("Información del video:")
        print(json.dumps(video_info, indent=4))
        
        # Obtener el mejor formato
        best_format = scraper.get_best_format(video_info['formats'])
        if best_format:
            print(f"\nMejor formato encontrado: {best_format['format_id']} - {best_format['url']}")
            
            # Descargar video con ffmpeg directamente desde la URL
            output_video = f"{video_info['title']}.mp4"
            # Limpiar el nombre del archivo
            output_video = re.sub(r'[<>:"/\\|?*]', '_', output_video)
            scraper.download_video_with_ffmpeg(best_format['url'], output_video, referer_url=video_url)
        else:
            print("No se encontraron formatos disponibles")
            
    except Exception as e:
        print(f"Error: {e}")
