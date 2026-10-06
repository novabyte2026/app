# Creators' App 3.5.0 — Hebrew native resources

הפרויקט מכין גרסה לא רשמית של חבילת ההתקנה שסופקה על ידי בעל המאגר. החבילה מיועדת ל־Android 13 ומעלה ולמכשירי ARM64.

התרגום מכסה משאבי Android: מחרוזות ממשק, הודעות, תיאורי נגישות, שלושה משאבי רבים ומערך מהירויות הניגון. מסכים המבוססים על Flutter מקומפל ב־`libapp.so` אינם מתורגמים באמצעות משאבים אלה. לתרגום מלא שלהם נדרש קוד המקור של Dart/Flutter.

## Current status

The generic build scripts and GitHub Actions workflow are present. The application payload and translated catalogue have not been published to this public repository. Until those inputs are available, Actions validates the scripts and explicitly skips APK compilation.

## Inputs

Place an authorized XAPK at `input/application.xapk` and its reviewed name-based resource catalogue at `input/translations.json`. The catalogue contains:

- `schema`: `1`
- `source_sha256`: SHA-256 of the exact reviewed XAPK
- `locale`: the language code
- `resource_qualifier`: Android resource qualifier (`iw` for Hebrew)
- `reference_locale`: source resource language (`en`)
- `strings`: resource-name to translated-text mapping
- `plurals`: resource-name to quantity/text mapping
- `array_items`: resource-name to item-index/text mapping

Run locally with Java 17 and Python 3.10 or later:

```sh
python3 scripts/build.py --source input/application.xapk --catalogue input/translations.json --output out
```

The script pins and verifies its packaging tools, merges splits, preserves executable code and assets, validates formatting, builds with Apktool's patched aapt2, aligns native libraries to 16 KiB, signs, verifies the signature, and checks resource values and IDs after decoding the compiled APK. It preserves legal resource text and technical identifiers not changed by the supplied catalogue.

## Signing

For a persistent PKCS12 key, add `--keystore`, `--password-file`, and optionally `--alias`. In Actions, use the secrets `SIGNING_KEYSTORE_B64`, `SIGNING_STORE_PASSWORD`, and optionally `SIGNING_KEY_ALIAS`. The key and store passwords must be the same. No signing key or password is committed or included in build artifacts.

Without a supplied key, a temporary key is generated. Separate runs then have different certificates and cannot update each other. An unofficial signature also cannot update an installation signed by Sony.

## Validation limits

A passing build proves resource compilation, byte preservation, alignment and signing. It does not prove that camera connections, Sony account sign-in or cloud features work with the modified signature. No physical phone/camera test has been performed. Flutter UI coverage must be reported separately.
