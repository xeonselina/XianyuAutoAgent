plugins {
    id("com.android.application")
}

android {
    namespace = "com.xianyu.cameraquality"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.xianyu.cameraquality"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0-probe"

        testInstrumentationRunner = "android.test.InstrumentationTestRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
