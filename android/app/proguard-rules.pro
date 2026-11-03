# The app keeps what Android reaches by name (activities, the worker, the provider) through the
# manifest and androidx's own rules.
# Ktor reads the JVM's uptime where it has one; Android has no java.lang.management.
-dontwarn java.lang.management.ManagementFactory
-dontwarn java.lang.management.RuntimeMXBean
