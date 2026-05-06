# Positive control corpus for SEC001 (hardcoded passwords).
# Annotation format: trailing comment on code lines only.
# DETECT means the scanner must flag that line.
# This corpus is not operational code and must never be deployed.

password = "IAmSensitive"                       # EXPECT: SEC001
password = "SummerVacation2024"                 # EXPECT: SEC001
admin_password = "CorrectHorseBatteryStaple"    # EXPECT: SEC001
db_password = "P@ssw0rd-Prod-2024"              # EXPECT: SEC001
user_password = "hunter2hunter2"                # EXPECT: SEC001
