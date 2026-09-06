import os
import yt_dlp
from pydub import AudioSegment
from tqdm import tqdm

# URL 입력받기
url_input = input('유튜브 URL을 입력하세요 (플레이리스트 또는 영상 URL): ').strip()
webm_dir = 'downloads'
mp3_dir = 'mp3s'
keepcharacters = (' ', '.', '_', '-')
verbose = False

def sanitize_filename(name):
    return ''.join(c for c in name if c.isalnum() or c in keepcharacters).rstrip()

def detect_leading_silence(sound, silence_threshold=-50.0, chunk_size=10):
    '''
    sound is a pydub.AudioSegment
    silence_threshold in dB
    chunk_size in ms

    iterate over chunks until you find the first one with sound
    '''
    trim_ms = 0  # ms

    assert chunk_size > 0  # to avoid infinite loop
    while sound[trim_ms:trim_ms + chunk_size].dBFS < silence_threshold and trim_ms < len(sound):
        trim_ms += chunk_size

    return trim_ms

def trim_silence(sound):
    start_trim = detect_leading_silence(sound)
    end_trim = detect_leading_silence(sound.reverse())
    if verbose:
        print('[.] Crop start %sms and end %sms' % (start_trim, end_trim))
    return sound[start_trim:len(sound) - end_trim]

def extract_entries(url):
    '''URL에서 영상 목록과 플레이리스트 제목을 가져온다.'''
    ydl_opts = {
        'quiet': True,
        'extract_flat': 'in_playlist',
        'ignoreerrors': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise ValueError('URL 정보를 가져올 수 없습니다.')

    if info.get('_type') == 'playlist':
        entries = [e for e in (info.get('entries') or []) if e]
        title = info.get('title') or 'playlist'
        return True, title, entries

    return False, info.get('title') or 'video', [info]

def download_audio_file(video_url, title_hint=''):
    '''오디오를 다운로드하고 로컬 파일 경로를 반환한다.'''
    outtmpl = os.path.join(webm_dir, '%(id)s.%(ext)s')
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': outtmpl,
        'quiet': not verbose,
        'no_warnings': not verbose,
        'noprogress': not verbose,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        if info is None:
            raise ValueError('다운로드 실패: %s' % (title_hint or video_url))
        filepath = ydl.prepare_filename(info)
        if not os.path.exists(filepath):
            # 확장자가 바뀐 경우 id로 탐색
            vid = info.get('id')
            matches = [f for f in os.listdir(webm_dir) if f.startswith(vid + '.')]
            if not matches:
                raise FileNotFoundError('다운로드된 파일을 찾을 수 없습니다: %s' % vid)
            filepath = os.path.join(webm_dir, matches[0])
        return info.get('title') or title_hint or info.get('id'), filepath

def download_and_trim(entry):
    '''영상을 다운로드하고 앞뒤 무음을 트림한 AudioSegment를 반환한다.'''
    video_url = entry.get('url') or entry.get('webpage_url') or entry.get('id')
    if video_url and not video_url.startswith('http'):
        video_url = 'https://www.youtube.com/watch?v=%s' % video_url

    title_hint = entry.get('title') or ''
    title, filepath = download_audio_file(video_url, title_hint)
    title = sanitize_filename(title)

    sound = AudioSegment.from_file(filepath)
    return title, trim_silence(sound)

def download_and_convert(entry):
    '''비디오를 다운로드하고 개별 MP3로 저장한다.'''
    try:
        title, trimmed_sound = download_and_trim(entry)
        mp3_path = os.path.join(mp3_dir, title + '.mp3')
        trimmed_sound.export(mp3_path, format='mp3', bitrate='192k')
        print('[+] 성공적으로 다운로드: %s' % title)
        return True
    except Exception as e:
        print('[!] 오류 발생: %s - %s' % (entry.get('title', 'unknown'), e))
        return False

def download_playlist_merged(playlist_title, entries):
    '''플레이리스트의 각 영상을 무음 트림한 뒤 하나의 MP3로 이어붙인다.'''
    merged = AudioSegment.empty()
    success_count = 0

    for entry in tqdm(entries):
        try:
            title, trimmed_sound = download_and_trim(entry)
            merged += trimmed_sound
            success_count += 1
            print('[+] 병합에 추가: %s' % title)
        except Exception as e:
            print('[!] 오류 발생: %s - %s' % (entry.get('title', 'unknown'), e))

    if success_count == 0:
        print('[!] 병합할 영상이 없습니다.')
        return False

    output_name = sanitize_filename(playlist_title) or 'playlist'
    mp3_path = os.path.join(mp3_dir, output_name + '.mp3')
    merged.export(mp3_path, format='mp3', bitrate='192k')
    duration_min = len(merged) / 1000 / 60
    print('[+] 하나로 이어붙여 저장: %s (%d개 영상, %.1f분)' % (mp3_path, success_count, duration_min))
    return True

os.makedirs(webm_dir, exist_ok=True)
os.makedirs(mp3_dir, exist_ok=True)

try:
    is_playlist, title, entries = extract_entries(url_input)
except Exception as e:
    print('[!] URL을 처리할 수 없습니다: %s' % e)
    raise SystemExit(1)

if is_playlist:
    print('[*] 플레이리스트 "%s"에 %d개의 영상이 있습니다!' % (title, len(entries)))
    print('다운로드 방식을 선택하세요:')
    print('  1) 각각 파일로 받기')
    print('  2) 전부 이어서 하나의 파일로 받기')
    mode = input('선택 (1/2): ').strip()

    if mode == '2':
        download_playlist_merged(title, entries)
    else:
        for entry in tqdm(entries):
            download_and_convert(entry)
else:
    print('[*] 단일 영상 다운로드: "%s"' % title)
    download_and_convert(entries[0])

print('[*] 완료!')
