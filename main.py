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

def ask_trim_seconds():
    '''인트로/아웃트로로 잘라낼 앞/뒤 초를 입력받는다.'''
    def ask(prompt):
        value = input(prompt).strip()
        if not value:
            return 0.0
        try:
            seconds = float(value)
        except ValueError:
            print('[!] 잘못된 입력입니다. 0초로 처리합니다.')
            return 0.0
        if seconds < 0:
            print('[!] 음수는 사용할 수 없습니다. 0초로 처리합니다.')
            return 0.0
        return seconds

    start_sec = ask('앞부분을 몇 초 잘라낼까요? (건너뛰려면 Enter): ')
    end_sec = ask('뒷부분을 몇 초 잘라낼까요? (건너뛰려면 Enter): ')
    return start_sec, end_sec

def download_and_trim(entry, skip_start_sec=0.0, skip_end_sec=0.0):
    '''영상을 다운로드하고 지정된 인트로/아웃트로를 잘라낸 뒤 앞뒤 무음을 트림한 AudioSegment를 반환한다.'''
    video_url = entry.get('url') or entry.get('webpage_url') or entry.get('id')
    if video_url and not video_url.startswith('http'):
        video_url = 'https://www.youtube.com/watch?v=%s' % video_url

    title_hint = entry.get('title') or ''
    title, filepath = download_audio_file(video_url, title_hint)
    title = sanitize_filename(title)

    sound = AudioSegment.from_file(filepath)

    start_ms = int(skip_start_sec * 1000)
    end_ms = int(skip_end_sec * 1000)
    if start_ms + end_ms < len(sound):
        sound = sound[start_ms:len(sound) - end_ms]
    elif verbose:
        print('[.] 잘라낼 길이가 영상 길이보다 길어 건너뛰기를 생략합니다: %s' % title)

    return title, trim_silence(sound)

def download_and_convert(entry, skip_start_sec=0.0, skip_end_sec=0.0):
    '''비디오를 다운로드하고 개별 MP3로 저장한다.'''
    try:
        title, trimmed_sound = download_and_trim(entry, skip_start_sec, skip_end_sec)
        mp3_path = os.path.join(mp3_dir, title + '.mp3')
        trimmed_sound.export(mp3_path, format='mp3', bitrate='192k')
        print('[+] 성공적으로 다운로드: %s' % title)
        return True
    except Exception as e:
        print('[!] 오류 발생: %s - %s' % (entry.get('title', 'unknown'), e))
        return False

def choose_first_entry(entries):
    '''사용자가 제목 일부를 입력해 1번으로 재생할 곡을 선택하면 해당 곡을 맨 앞으로 옮긴 목록을 반환한다.'''
    keyword = input('1번으로 재생할 곡의 제목 일부를 입력하세요 (건너뛰려면 Enter): ').strip()
    if not keyword:
        return entries

    keyword_lower = keyword.lower()
    matches = [
        (i, entry) for i, entry in enumerate(entries)
        if keyword_lower in (entry.get('title') or '').lower()
    ]

    if not matches:
        print('[!] "%s"이(가) 포함된 곡을 찾을 수 없습니다. 원래 순서를 사용합니다.' % keyword)
        return entries

    if len(matches) == 1:
        index, entry = matches[0]
        print('[*] 선택된 곡: %s' % (entry.get('title') or entry.get('id') or 'unknown'))
    else:
        print('[*] "%s"이(가) 포함된 곡이 여러 개 있습니다:' % keyword)
        for n, (i, entry) in enumerate(matches, start=1):
            print('  %d) %s' % (n, entry.get('title') or entry.get('id') or 'unknown'))

        choice = input('번호를 선택하세요 (건너뛰려면 Enter): ').strip()
        if not choice:
            return entries

        try:
            pick = int(choice) - 1
        except ValueError:
            print('[!] 잘못된 입력입니다. 원래 순서를 사용합니다.')
            return entries

        if pick < 0 or pick >= len(matches):
            print('[!] 범위를 벗어난 번호입니다. 원래 순서를 사용합니다.')
            return entries

        index, entry = matches[pick]

    reordered = [entries[index]] + entries[:index] + entries[index + 1:]
    return reordered

def download_playlist_merged(playlist_title, entries, skip_start_sec=0.0, skip_end_sec=0.0):
    '''플레이리스트의 각 영상을 무음 트림한 뒤 하나의 MP3로 이어붙인다.'''
    merged = AudioSegment.empty()
    success_count = 0

    for entry in tqdm(entries):
        try:
            title, trimmed_sound = download_and_trim(entry, skip_start_sec, skip_end_sec)
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
    skip_start_sec, skip_end_sec = ask_trim_seconds()

    if mode == '2':
        entries = choose_first_entry(entries)
        download_playlist_merged(title, entries, skip_start_sec, skip_end_sec)
    else:
        for entry in tqdm(entries):
            download_and_convert(entry, skip_start_sec, skip_end_sec)
else:
    print('[*] 단일 영상 다운로드: "%s"' % title)
    skip_start_sec, skip_end_sec = ask_trim_seconds()
    download_and_convert(entries[0], skip_start_sec, skip_end_sec)

print('[*] 완료!')
