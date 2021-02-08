# source: https://www.esrl.noaa.gov/gmd/grad/solcalc/solareqns.PDF

from datetime import datetime, tzinfo
import math


now = datetime.now()
day_of_year = (now - datetime(now.year, 1, 1)).days
hour = 0

# gamma
fractional_year = 2*math.pi*(day_of_year-1+(hour-12)/24)/365

print(f'Fractional year = {fractional_year} [rad]')

#decl = 0.006918 – 0.399912cos(γ) + 0.070257sin(γ) – 0.006758cos(2γ) + 0.000907sin(2γ) – 0.002697cos(3γ) + 0.00148sin (3γ)
declination_angle = 0.006918-0.399912*math.cos(fractional_year)\
                    + 0.070257*math.sin(fractional_year) \
                    - 0.006758*math.cos(2*fractional_year) \
                    + 0.000907*math.sin(2*fractional_year) \
                    - 0.002697*math.cos(3*fractional_year) \
                    + 0.00148*math.sin(3*fractional_year)

print(f'Declination angle = {declination_angle}')

# eqtime = 229.18*(0.000075 + 0.001868cos(γ) – 0.032077sin(γ) – 0.014615cos(2γ) – 0.040849sin(2γ) )
equation_of_time = 229.18*(0.000075 + 0.001868*math.cos(fractional_year)
                           - 0.032077*math.sin(fractional_year)
                           - 0.014615*math.cos(2*fractional_year)
                           - 0.040849*math.sin(2*fractional_year))

print(f'Equation of time = {equation_of_time}')

lattitude_deg = 49.993906
longitude_deg = 19.96859


print(f'Lattitude: {lattitude_deg}, longitude: {longitude_deg} [degrees]')

hour_angle_deg = -math.degrees(
    math.acos(
        (math.cos(math.radians(90.833))/(math.cos(math.radians(lattitude_deg)) * math.cos(declination_angle)))
        - math.tan(math.radians(lattitude_deg))*math.tan(declination_angle)))


sunset = 720 - 4 * (longitude_deg + hour_angle_deg) - equation_of_time

print(f'Sunset: {sunset} [min] == {int(sunset/60)}:{int(sunset%60)}')

utc = datetime.utcnow().replace(hour=int(sunset/60), minute=int(sunset%60), second=0, microsecond=0)
cest = utc.astimezone()

diff = cest -  datetime.utcnow().astimezone()

print(f'Sunset is at: {utc} UTC, {cest} CEST, now: {datetime.utcnow().astimezone()}, diff: {diff}, final: {(cest+cest.utcoffset()).replace(tzinfo=None)}')






