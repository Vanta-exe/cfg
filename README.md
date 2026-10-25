# Crimson CFG community

Crimson Drake topluluk ayarları. Sunucu, VDS, veritabanı veya ayrı bir servis gerekmez.
Panel bu reponun `main` dalındaki `catalog.json` dosyasını okur.

## Kullanım

1. **Ayarlar → Profiller → GitHub bağlantısı** bölümünü aç.
2. Kendi GitHub hesabından süreli bir **personal access token (classic)** oluştur;
   herkese açık bir repoda issue oluşturabilmek için `public_repo` izni gerekir.
   Token bu uygulama için Windows DPAPI ile şifrelenir. Lisans anahtarını buraya girme.
3. Kayıtlar bölümünde isim ve açıklama girip **Kaydet ve paylaş** düğmesine bas.
4. GitHub Actions doğrulamayı bitirince kayıt Topluluk bölümünde görünür.
   Topluluk sekmesini açmak veya Yenile'ye basmak güncel listeyi getirir.
5. Bir kaydı seçip **CFG indir** düğmesine bas. Kayıt yerel listeye eklenir;
   uygulanması için ayrıca **Profili yükle** seçilir.

Okuma ve indirme için GitHub hesabı gerekmez. Yayınlamak için her kişi kendi
hesabını kullanır; uygulamanın içine repo sahibi tokenı veya ortak yazma anahtarı konmaz.
`public_repo` kapsamı hesabının diğer public repolarını da kapsar: yalnızca bu
uygulama için kısa süreli token kullanabilir, sonrasında GitHub ayarlarından iptal edebilirsin.

Paylaşımlar herkese açıktır. Sadece sayısal özellik ayarları yayınlanır.
Kimlik bilgileri, lisanslar, GitHub tokenı, GUI tercihleri, yerleşim, runtime
adresleri/imzaları, koruma ayarları ve menü/durdurma tuşları paylaşılmaz.
İndirilen kayıt uygulanırken yerel koruma, arayüz, yerleşim ve kurulum bilgileri korunur.

## Nasıl çalışır?

- Her CFG bir GitHub issue'sudur. Gerçek yazar issue sahibidir; gövde içindeki
  bir `author` alanına güvenilmez. Aynı yerel kayıt tekrar paylaşılınca kendi
  issue'su güncellenir; başka birinin kaydı paylaşılınca yeni bir issue oluşur.
- `CFG community` workflow'u issue açma/düzenleme/yeniden açma/kapatma olaylarını işler.
  İçerik veri olarak ayrıştırılır; issue metni komuta veya çalıştırılan koda dönüşmez.
- Doğrulanan dosya `configs/<issue>/config.ini`, ayrıntıları `metadata.json`
  ve liste `catalog.json` olarak tek bir Git commit'inde yayınlanır.
- Her issue için `cfg-<issue>` release'i vardır. Her revizyon SHA-256 adında
  değiştirilmeyen `.ini` asset'idir. Mevcut revizyon yeniden yüklenip silinmez.
- İndirme sayısı bu release'in bütün `.ini` revizyonlarının gerçek GitHub
  `download_count` değerlerinin toplamıdır. Bu sayı tekil kişi sayısı değildir;
  aynı kişinin tekrar indirmeleri ve GitHub'dan doğrudan indirmeleri de dahildir.
  Gösterilen değer GitHub'ın raporudur; anında güncellenmesi garanti edilmez.
  Canlı kurulum testinde dosya başarıyla indirilirken API henüz `0` bildirdi.
- Saatlik workflow istatistikleri kataloğa yazar. Panel Yenile sırasında GitHub
  release sayılarını da okur. API sınırına ulaşılırsa son yayınlanan sayılar
  önbellek etiketiyle gösterilir; sahte artış yapılmaz.
- Yazar **Paylaşımı kaldır** ile issue'yu kapatabilir. Katalogdan kaldırılır;
  Git geçmişi ve eski release dosyaları korunur. Bu işlem internetteki geçmişi silmez.
- Saatlik/elle başlatılan çalışma son güncellenen 1.000 issue'yu uzlaştırır;
  peş peşe tetiklemelerde atlanan işlemleri toparlar. API erişim kesintilerinde
  yayın gecikebilir; paneldeki issue bağlantısından workflow durumu izlenebilir.

Sınırlar: 48.000 bayt CFG, 80 bayt isim, 500 bayt açıklama, 1.000 sayısal alan,
katalogda 1.000 CFG, kişi başına 30 etkin CFG, CFG başına 100 revizyon.
Bu kurulum GitHub API ve Actions kotalarına tabidir.

## İlk kurulum (repo sahibi)

1. `.github/workflows/cfg-community.yml`, `.github/scripts/`, `catalog.json`,
   `.gitignore` ve bu README dosyasını bu reponun **main** dalına ekle.
   GitHub'ın web arayüzünden yüklerken gizli `.github` klasörünü de eklediğinden emin ol.
2. Repo **public**, Issues ve Actions açık olmalı. Workflow dosyası kendi
   `contents: write` ve `issues: write` izinlerini tanımlar; ek secret gerekmez.
   Üst organizasyon politikaları bu izinleri engelliyorsa repo sahibi düzenlemelidir.
3. Actions → **CFG community** → **Run workflow** ile ilk çalışmayı doğrula.
   Workflow dosyası push edildiğinde de otomatik test çalışır.
4. Panelden bir CFG paylaş; issue workflow'u başarılı olduktan sonra
   `catalog.json`, `configs/` ve Releases bölümünü kontrol et.

Workflow'un indirme/commit yazma yetkisi GitHub'ın kısa ömürlü `GITHUB_TOKEN`
değerinden gelir. Bu token uygulamaya veya CFG dosyalarına gönderilmez.
Workflow kodunu yalnızca güvenilen repo yöneticileri değiştirmelidir.

## Test

```powershell
python -m unittest discover -s .github/scripts -p 'test_*.py'
```

Testler yayınlama, yazar kimliği, revizyon güncelleme, liste dışına çıkarma,
gerçek sayaçların birleştirilmesi, kayıp olay uzlaştırması ve geçersiz içeriğin
Git'e ulaşmadan reddedilmesini denetler. Gerçek hesaba yazmadan çalışırlar.
cfg
