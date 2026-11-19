<div dir="rtl">

# PhantomRoute — نسخة Termux (Android)

تدوير بلد الخروج في Tor على أندرويد بدون Root.

## المتطلبات

- تطبيق **Termux** (يُفضّل من F-Droid)
- اتصال بالإنترنت

## التثبيت

```bash
pkg update -y && pkg install -y git
git clone https://github.com/Black-ghost7/PhantomRoute.git
cd PhantomRoute/PhantomRoute-Termux
chmod +x install.sh
./install.sh
```

## الاستخدام

```bash
phantomroute                    # تشغيل
phantomroute --interval 60      # تدوير كل 60 ثانية
phantomroute --status           # عرض الحالة
phantomroute --panic            # استعادة بعد انهيار
```

## توجيه أوامر عبر Tor

بعد تشغيل الأداة يعمل Tor على `127.0.0.1:9050`:

```bash
pkg install torsocks
torsocks curl https://check.torproject.org/api/ip

# أو
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip
```

## الفروقات عن نسخة Kali

- لا يوجد `systemd`: يعمل Tor كعملية فرعية، ويُوقف ويُستعاد `torrc` عند الخروج.
- لا يوجد Kill Switch (قيود أندرويد): التطبيقات **لا تمر عبر Tor تلقائياً**، فقط ما توجّهه أنت.
- لا يوجد تغيير لـ MAC أو Hostname.
- حماية DNS محدودة بدون Root.

</div>
