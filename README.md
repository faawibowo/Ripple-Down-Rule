# RDR: Rekomendasi Alat Musik untuk Pemula

Sistem pakar berbasis **Ripple Down Rules (RDR)** untuk membantu pemilik toko musik (pakar)
merekomendasikan alat musik kepada pelanggan pemula. Pengetahuan tidak ditulis di awal, tetapi
dibangun bertahap: sistem dimulai dari satu rule default, lalu pakar menambah rule perkecualian
setiap kali rekomendasi sistem dianggap salah.

## Cara kerja singkat

- KB berupa **pohon biner**. Setiap node punya kondisi (gabungan AND), kesimpulan, dan
  *cornerstone case* (kasus yang memicu pembuatan node itu).
- **true-child** = perkecualian, dievaluasi jika kondisi node terpenuhi.
  **false-child** = alternatif, dievaluasi jika kondisi node tidak terpenuhi.
- Inferensi menelusuri pohon dari root. Kesimpulan yang diberikan adalah kesimpulan **terakhir**
  yang terpenuhi, karena kesimpulan sebelumnya sudah dianulir oleh perkecualiannya.
- Jika pakar tidak setuju, pakar memberi kesimpulan yang benar dan memilih kondisi dari
  **difference list**: kondisi yang benar untuk kasus baru dan salah untuk cornerstone case node
  yang dianulir. Rule baru dipasang sebagai true-child (jika node terakhir terpenuhi) atau
  false-child (jika tidak) dari node terakhir yang dievaluasi.

KB awal hanya berisi `t → Gitar akustik`.

## Domain dan atribut

| Atribut | Jenis | Nilai |
|---|---|---|
| `budget` | numerik | 0 sampai 30.000.000 (Rp) |
| `umur` | numerik | 4 sampai 80 |
| `jam_latihan` | numerik | 0 sampai 40 (jam/minggu) |
| `genre` | kategorikal | pop, rock, jazz, klasik, edm |
| `tempat_tinggal` | kategorikal | rumah, kos |
| `nyanyi_sambil_main` | kategorikal | ya, tidak |
| `punya_laptop` | kategorikal | ya, tidak |

Operator kondisi: numerik `<  <=  >  >=  =`, kategorikal `=  !=`.

Kesimpulan yang tersedia: Gitar akustik, Gitar akustik 3/4, Ukulele, Gitar elektrik + amplifier,
Gitar elektrik + headphone amp, Keyboard 61 tuts, Digital piano 88 tuts, MIDI keyboard,
Keyboard portabel. Pakar juga bisa mengisi kesimpulan baru lewat opsi "Lainnya".

Atribut dan kesimpulan didefinisikan di `schema.json`. Form di UI dibuat otomatis dari file itu.

## Instalasi dan menjalankan

Butuh Python 3.9 atau lebih baru.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Aplikasi terbuka di `http://localhost:8501`.

## Cara memakai

1. **Konsultasi.** Isi form pelanggan, lalu klik **Minta Rekomendasi**. Hasil menampilkan
   kesimpulan dan tabel trace (node yang dievaluasi, terpenuhi atau tidak, dan node yang dipakai
   ditandai ★).
2. **Setuju.** Rekomendasi diberikan dan KB tidak berubah.
3. **Tidak setuju.** Pilih kesimpulan yang benar, lihat perbandingan kasus baru dengan cornerstone
   case, centang kondisi dari difference list, lalu **Simpan rule**. Untuk kondisi numerik,
   operator dan nilai batas boleh diedit. Aplikasi memvalidasi bahwa kondisi benar untuk kasus
   baru dan tidak berlaku untuk cornerstone case, dan menolak rule yang merusak kasus lama.
4. **Tab Tree KB** menampilkan pohon (edge hijau = true, merah = false) dengan jalur konsultasi
   terakhir disorot, plus tampilan teks yang bisa disalin ke laporan.
5. **Sidebar** menampilkan jumlah rule, status konsistensi KB, serta tombol Save, Load, dan Reset.
   KB disimpan otomatis ke `kb.json` setiap kali rule baru ditambahkan, dan dimuat otomatis saat
   aplikasi dijalankan kalau file itu ada.

### Demo cepat dengan skenario

`scenario.json` berisi 12 kasus berurutan (dari KB kosong) lengkap dengan jawaban pakar dan
kondisi yang dipilih. Di bagian Konsultasi, pilih nomor skenario lalu klik **Isi dari skenario**
untuk memuat kasusnya ke form. Panel "Naskah demo" menampilkan apa yang harus dilakukan pakar.
Jalankan skenario 1 sampai 12 berurutan setelah **Reset KB**, dan tree akhir akan sama dengan
`expected_final_tree` di `scenario.json`.

## Struktur proyek

```
schema.json     atribut, kesimpulan, dan kesimpulan default
rdr.py          engine RDR (node, inferensi, difference list, validasi, simpan/muat)
app.py          antarmuka Streamlit
test_rdr.py     unit test engine dan replay skenario
scenario.json   12 kasus uji sekaligus naskah demo, beserta tree akhir yang diharapkan
kb.json         KB tersimpan, dihasilkan program
```

## Tes

```bash
pytest
```

Tes menjalankan seluruh `scenario.json` dari KB kosong dan memeriksa kesimpulan sistem, struktur
tree, serta konsistensi KB setelah setiap rule.
