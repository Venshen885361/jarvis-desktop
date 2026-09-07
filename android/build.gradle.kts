// Android Studio 開啟時若提示升級 AGP / Kotlin，直接接受即可；這組版本是已知能互相配合的組合。
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
