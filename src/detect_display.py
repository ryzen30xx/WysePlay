import subprocess, re, sys

def get_display_mode():
    try:
        output = subprocess.check_output('DISPLAY=:0 xrandr', shell=True).decode()
        for line in output.splitlines():
            if '*' in line:
                parts = line.split()
                res = parts[0]
                rate = 60
                for p in parts[1:]:
                    if '*' in p:
                        clean_rate = re.sub(r'[^0-9.]', '', p)
                        try:
                            rate = int(round(float(clean_rate)))
                        except Exception:
                            rate = 60
                # Cap rate to max 60 fps for Apple AirPlay compatibility
                effective_rate = min(rate, 60)
                return res, effective_rate
    except Exception as e:
        pass
    return '1920x1080', 60

if __name__ == '__main__':
    res, rate = get_display_mode()
    print(f'{res} {rate}')
