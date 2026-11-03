pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "caracole-android"
// mirror: the computer's pages on the phone; core: caracole's rules in Kotlin; server: the phone's local server;
// app: the Android app; e2e: the end-to-end phases against a real caracole serve.
include(":mirror", ":core", ":server", ":app", ":e2e")
