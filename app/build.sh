#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
ANDROID_JAR="${ANDROID_JAR:-$HOME/termux-adb-bridge/build/adbwifi-helper/android.jar}"
[ -f "$ANDROID_JAR" ] || { echo "android.jar not found at $ANDROID_JAR" >&2; exit 1; }
rm -rf build
mkdir -p build/classes build/gen build/dex
aapt2 compile --dir res -o build/res.zip
aapt2 link -o build/base.apk -I "$ANDROID_JAR" --manifest AndroidManifest.xml \
  build/res.zip --java build/gen --min-sdk-version 26 --target-sdk-version 30 \
  --version-code 1 --version-name 1.0
javac -source 8 -target 8 -Xlint:-options -bootclasspath "$ANDROID_JAR" \
  -cp "$ANDROID_JAR" -d build/classes $(find src build/gen -name '*.java')
d8 --min-api 26 --lib "$ANDROID_JAR" --output build/dex \
  $(find build/classes -name '*.class')
python3 -c "import zipfile;z=zipfile.ZipFile('build/base.apk','a');z.write('build/dex/classes.dex','classes.dex');z.close()"
if [ ! -f keystore.jks ]; then
  keytool -genkeypair -keystore keystore.jks -alias miband -keyalg RSA -keysize 2048 \
    -validity 10000 -storepass mibandbridge -keypass mibandbridge -dname "CN=miband bridge"
fi
zipalign -f 4 build/base.apk build/aligned.apk
apksigner sign --ks keystore.jks --ks-pass pass:mibandbridge --key-pass pass:mibandbridge \
  --out mibandbridge.apk build/aligned.apk
apksigner verify mibandbridge.apk && echo "OK app/mibandbridge.apk"