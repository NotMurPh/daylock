"""Find the Deadlock install.

Order: the DEADLOCK_DIR environment variable (your ...\\steamapps\\common\\Deadlock folder), then every Steam
library listed in Steam's libraryfolders.vdf, then the default Steam folder.
"""
import os
import re

DEFAULT_STEAM = r'C:\Program Files (x86)\Steam'


def steam_dir():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            return os.path.normpath(winreg.QueryValueEx(k, 'SteamPath')[0])
    except (ImportError, OSError):
        return DEFAULT_STEAM


def _libraries(steam):
    libs = [steam]
    try:
        text = open(os.path.join(steam, 'steamapps', 'libraryfolders.vdf'), encoding='utf-8', errors='replace').read()
    except OSError:
        return libs
    libs += [os.path.normpath(m.replace('\\\\', '\\')) for m in re.findall(r'"path"\s+"([^"]+)"', text)]
    return libs


def deadlock_dir():
    env = os.environ.get('DEADLOCK_DIR')
    if env:
        if os.path.isfile(os.path.join(env, 'game', 'citadel', 'gameinfo.gi')):
            return os.path.normpath(env)
        raise SystemExit('DEADLOCK_DIR=%s is not a Deadlock folder (no game\\citadel\\gameinfo.gi)' % env)
    for lib in _libraries(steam_dir()) + [DEFAULT_STEAM]:
        d = os.path.join(lib, 'steamapps', 'common', 'Deadlock')
        if os.path.isfile(os.path.join(d, 'game', 'citadel', 'gameinfo.gi')):
            return os.path.normpath(d)
    raise SystemExit('Deadlock not found. Set DEADLOCK_DIR to your ...\\steamapps\\common\\Deadlock folder.')


def citadel():
    """...\\Deadlock\\game\\citadel"""
    return os.path.join(deadlock_dir(), 'game', 'citadel')


if __name__ == '__main__':
    print(citadel())
