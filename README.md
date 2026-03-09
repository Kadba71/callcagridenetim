# Çağrı Denetim Telegram Botu

Bu proje, Telegram üzerinden yüklenen Excel çağrı raporlarını departman bazlı kurallara göre denetler.

## Özellikler

- `/help`, `/departmanekle`, `/departmansil`, `/departmanliste`
- `/izin`, `/izinsil`, `/izinliste`
- `/sorumluekle`, `/sorumlusil`, `/sorumluliste`
- `/kuralekle`, `/kuralgoster`, `/kuralliste`, `/kuralsil`, `/cagriaraligi`
- `/sabahengec`, `/molaoncesi`, `/molaaraligi`, `/molasonrasi`, `/mesaisonu`
- `/durum`, `/yukle <departman>`
- Excel dosyasından yalnızca `isim-O` kayıtlarını dikkate alma
- Departman bazlı kural tanımı
- Sorumlu eşleştirme
- İhlal raporunu mesaj ve Excel olarak üretme
- Departman adlarını normalize etme (`diş ekip`, `DİŞ EKİP`, `Diş    Ekip` aynı kabul edilir)
- Uzun Telegram raporlarını parçalara bölerek gönderme
- Verileri SQLite veritabanında kalıcı saklama

## Kurulum

1. Python 3.11+ kurulu olmalı.
2. Bu klasörde sanal ortam açın.
3. Paketleri yükleyin:
   - `pip install -r requirements.txt`
4. `.env.example` dosyasını `.env` olarak kopyalayın.
5. `.env` içine Telegram bot token değerini yazın.
6. Gerekirse veritabanı yolunu ayarlayın:
   - `DATABASE_PATH=data/bot.db`
7. Botu çalıştırın:
   - `python bot.py`
8. Testleri çalıştırın:
   - `pytest`

## Railway

Railway üzerinde departmanlar, kurallar, sorumlular ve izinli personeller SQLite veritabanında saklanır.
Bu verilerin kalıcı kalması için Railway Volume kullanın ve `DATABASE_PATH` değişkenini volume içindeki dosyaya yönlendirin.

Örnek:

- Volume mount path: `/app/data`
- `DATABASE_PATH=/app/data/bot.db`

## Kural formatı

`/kuralekle <departman>, <max_bekleme_dk>, <sabah_en_gec>, <mola_oncesi_en_erken>, <mola_baslangic-mola_bitis>, <mola_sonrasi_en_gec>, <mesai_sonu_en_erken>`

Örnek:

`/kuralekle Satış, 15, 08:30, 11:55, 12:00-13:00, 13:10, 18:00`

Sadece çağrı aralığını güncellemek için:

`/cagriaraligi 20, Satış`

Diğer alanları tek tek güncellemek için:

- `/sabahengec 08:45, Satış`
- `/molaoncesi 11:50, Satış`
- `/molaaraligi 12:00-13:00, Satış`
- `/molasonrasi 13:10, Satış`
- `/mesaisonu 18:00, Satış`

Saatler şu sıraya uygun olmalıdır:

`sabah < mola öncesi < mola başlangıç < mola bitiş <= mola sonrası <= mesai sonu`

Excel yüklemek için:

`/yukle Satış`

Belirli bir saate kadar anlık kontrol için:

`/yukle Satış, 12:00`

Bu kullanımda bot sadece `12:00`'ye kadar raporda görünen veriyi değerlendirir. `12:00` sonrasında gerçekleşecek veya raporda henüz görünmeyen çağrılar ihlal hesabına katılmaz.

## Listeleme komutları

- `/departmanliste`
- `/izinliste`
- `/sorumluliste Satış`
- `/kuralgoster Satış`
- `/kuralliste`
- `/durum`

## İzinli personel

- `/izin Ahmet Yılmaz`
- `/izinsil Ahmet Yılmaz`

İzinli olarak eklenen personeller analiz sırasında kontrol edilmez.

## Excel beklentisi

- `ARAMA TARİHİ`
- `ARAMA SAATİ`
- `KONUŞMA SÜRESİ`
- `ÇALDIRMA SÜRESİ`
- `DAHİLİ ADI`

Bot, `DAHİLİ ADI` alanında sadece `isim-O` olan personelleri analiz eder. `isim-K` kayıtları dikkate alınmaz. Analiz edilecek departman, `/yukle <departman>` komutunda gönderilen değerden alınır.
