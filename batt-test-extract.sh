#!/bin/sh

awk '
function to24(t, ap, h, m, s) {
    split(t, a, ":")
    h = a[1] + 0
    m = a[2]
    s = a[3]

    if (ap == "PM" && h < 12) h += 12
    if (ap == "AM" && h == 12) h = 0

    return sprintf("%02d:%02d:%02d", h, m, s)
}

NR % 3 == 1 {
    time = to24($4, $5)
}

NR % 3 == 2 {
    line = $0
    sub(/^.*battery_volts:[ ]*/, "", line)
    volts = line
    sub(/,.*/, "", volts)

    line = $0
    sub(/^.*battery_perc:[ ]*/, "", line)
    perc = line
    sub(/,.*/, "", perc)

    print time "," volts "," perc
}
' $1
