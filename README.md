# Creators' App 3.5.0 — Hebrew localization work

Build project for the installation package supplied by the repository owner. The source package targets Android 13+ and ARM64 devices.

The work includes contextual Hebrew translation of Android string resources and GitHub Actions packaging/signing. The original app also contains precompiled Flutter localization tables in `libapp.so`; coverage of those screens must be reported separately and must not be inferred from a successful Android resource build.

The localization and validation reports will document translated resources, preserved technical identifiers, build checks, and remaining limitations. Signing uses an independently generated key; the result is an unofficial modified package and cannot replace an installation signed by Sony.

No signing private keys or passwords will be committed to this repository.
