import os
from pydub import AudioSegment
import pafy
from tqdm import tqdm

pafy.set_api_key('YOUR-YOUTUBE-API-KEY-HERE')

playlist_url = 'https://www.youtube.com/playlist?list=PL1Vg2mFKnxG745JV9pWSt-onYmT1GG6BS'
webm_dir = 'downloads'
mp3_dir = 'mp3s'
keepcharacters = (' ', '.', '_', '-')
verbose = False

def detect_leading_silence(sound, silence_threshold=-50.0, chunk_size=10):
    '''
    sound is a pydub.AudioSegment
    silence_threshold in dB
    chunk_size in ms

    iterate over chunks until you find the first one with sound
    '''
    trim_ms = 0 # ms

    assert chunk_size > 0 # to avoid infinite loop
    while sound[trim_ms:trim_ms+chunk_size].dBFS < silence_threshold and trim_ms < len(sound):
        trim_ms += chunk_size

    return trim_ms

os.makedirs(webm_dir, exist_ok=True)
os.makedirs(mp3_dir, exist_ok=True)

playlist = pafy.get_playlist2(playlist_url)

print('[*] Playlist "%s" has %d songs!' % (playlist.title, len(playlist)))

for i, song in enumerate(tqdm(playlist)):
    title = song.title
    title = ''.join(c for c in title if c.isalnum() or c in keepcharacters).rstrip()

    webm_path = os.path.join(webm_dir, title + '.webm')
    mp3_path = os.path.join(mp3_dir, title + '.mp3')

    if verbose:
        print('[.] Downloading %d: %s' % (i + 1, title))

    try:
        yt_audio = song.getbestaudio(preftype='webm')
        yt_audio.download(filepath=webm_path, quiet=(not verbose))

        sound = AudioSegment.from_file(webm_path)

        start_trim = detect_leading_silence(sound)
        end_trim = detect_leading_silence(sound.reverse())
        if verbose:
            print('[.] Crop start %sms and end %sms' % (start_trim, end_trim))

        trimmed_sound = sound[start_trim:len(sound)-end_trim]
        trimmed_sound.export(mp3_path, format='mp3', bitrate='192k')
    except Exception as e:
        print(i, title, e)

print('[*] Done!')
