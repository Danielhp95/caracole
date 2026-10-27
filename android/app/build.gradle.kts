import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "io.github.danielhp95.caracole"
    // flake.nix's platformVersion and buildToolsVersion: the SDK the shell provides.
    compileSdk = 36
    buildToolsVersion = "36.0.0"

    defaultConfig {
        applicationId = "io.github.danielhp95.caracole"
        minSdk = 26
        // 36, not 37: an app targeting Android 17 must ask for ACCESS_LOCAL_NETWORK to reach a LAN address.
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    // No dependency metadata in the APK: nothing a store could read about the build that isn't in it.
    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }

    packaging {
        resources.excludes += setOf("META-INF/*.version", "META-INF/*.kotlin_module", "DebugProbesKt.bin")
    }
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation(project(":mirror"))
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.work:work-runtime-ktx:2.10.5")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:core-ktx:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.espresso:espresso-intents:3.7.0")
}
