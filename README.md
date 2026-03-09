# Çağrı Denetim Telegram Botu

Bu proje, Telegram üzerinden yüklenen çağrı raporlarını analiz eden bir denetim botudur.

## Proje Mantığı

Botun temel amacı, departman bazlı çalışma düzenini tek merkezden takip etmektir.

- Her departman için ayrı kurallar tanımlanır.
- Personellerin çağrı başlangıç, bekleme ve mesai davranışları bu kurallara göre değerlendirilir.
- İzinli personeller analiz dışında bırakılır.
- Sorumlu eşleştirmeleri ile raporlar daha anlamlı hale getirilir.
- Gerekirse mesai sonrası çalışma özeti alınabilir.

## Genel Akış

1. Departman ve kural tanımları yapılır.
2. Excel çağrı raporu Telegram üzerinden yüklenir.
3. Bot raporu analiz eder.
4. İhlal varsa personel bazlı sonuç üretir.
5. İstenirse belirli bir saat sonrası çalışma özeti çıkarır.

## Veri Yapısı

Bot aşağıdaki verileri kalıcı olarak saklar:

- Departmanlar
- Departman kuralları
- Sorumlular
- İzinli personeller

## Amaç

Çağrı operasyonunu manuel kontrol yerine daha tutarlı, hızlı ve izlenebilir hale getirmek.
