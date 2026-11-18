"""Atur kata sandi HPP Studio (gerbang login).

Jalankan:
    python set_password.py

Skrip akan meminta kata sandi baru dua kali (input tersembunyi), menghitung
hash SHA-256-nya, lalu MENULIS berkas lokal app/config/password_local.py.
Berkas itu di-ignore oleh git sehingga hash tidak pernah ikut ke repositori.
Tanpa berkas itu aplikasi menolak semua kata sandi.
"""
from __future__ import annotations
import getpass
import hashlib
import os
import sys

LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'app', 'config', 'password_local.py')


def main() -> int:
    if not os.path.isdir(os.path.dirname(LOCAL_PATH)):
        print(f'[GAGAL] Folder tidak ditemukan: {os.path.dirname(LOCAL_PATH)}')
        return 1

    # input tersembunyi bila terminal mendukung; jika tidak (mis. IDE),
    # getpass otomatis fallback ke input biasa dengan peringatan.
    pw1 = getpass.getpass('Kata sandi baru        : ')
    if not pw1:
        print('[BATAL] Kata sandi kosong — tidak ada perubahan.')
        return 1
    pw2 = getpass.getpass('Ulangi kata sandi baru : ')
    if pw1 != pw2:
        print('[GAGAL] Dua masukan tidak sama — tidak ada perubahan.')
        return 1

    new_hash = hashlib.sha256(pw1.encode('utf-8')).hexdigest()

    with open(LOCAL_PATH, 'w', encoding='utf-8') as f:
        f.write('# Dibuat oleh set_password.py — JANGAN di-commit ke git.\n')
        f.write(f'PASSWORD_SHA256 = "{new_hash}"\n')

    print('\n[OK] Kata sandi diperbarui.')
    print(f'     Disimpan di {LOCAL_PATH}')
    print('     Berlaku saat aplikasi dibuka berikutnya.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
