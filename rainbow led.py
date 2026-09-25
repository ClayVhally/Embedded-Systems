"""Rainbow RGB LED project for a Raspberry Pi computer (Raspberry Pi OS).

Hardware: one low-current, four-leg COMMON-CATHODE RGB LED, three 330-ohm
resistors, jumper wires, and a breadboard. Confirm the LED legs from its
datasheet; their order varies. Disconnect power before wiring.

    Red leg   -> 330-ohm resistor -> BCM GPIO17 (physical pin 11)
    Green leg -> 330-ohm resistor -> BCM GPIO27 (physical pin 13)
    Blue leg  -> 330-ohm resistor -> BCM GPIO22 (physical pin 15)
    Common cathode               -> GND        (physical pin 6)

Use one resistor per color. GPIO signals are 3.3 V; never connect them to 5 V.
This example is for a small bare RGB LED, not an LED strip or a Pico board.
A normal single-color LED cannot change to rainbow colors.

From your repository root on Raspberry Pi OS:
    sudo apt update
    sudo apt install python3-gpiozero python3-lgpio python3-venv
    python3 -m venv --system-site-packages .venv
    source .venv/bin/activate
    python raspberry_pi/led.py

On Windows, use your activated project environment:
    python -m pip install gpiozero==2.0.1
    python raspberry_pi/led.py --simulate --cycles 1

Simulation prints RGB values; it does not show a colored window or use GPIO.
Press Ctrl+C to stop. The program turns off the LED before releasing the pins.
Reference: https://gpiozero.readthedocs.io/en/stable/api_output.html#rgbled
"""

import argparse
from colorsys import hsv_to_rgb
from time import sleep

# Adjust these to change the speed and brightness of your rainbow.
STEP_DELAY = 0.02       # Seconds per color step; a full rainbow takes ~7.2 s.
BRIGHTNESS = 0.5        # 0.0 is off; 1.0 is the maximum duty cycle.


def rainbow(led, cycles=0, simulate=False):
    """Move smoothly around the color wheel; zero cycles means keep going."""
    completed = 0
    try:
        while cycles == 0 or completed < cycles:
            for hue in range(360):
                # Hue selects a color; HSV conversion gives its red/green/blue mix.
                led.color = hsv_to_rgb(hue / 360, 1.0, BRIGHTNESS)
                if simulate and hue % 60 == 0:
                    red, green, blue = led.value
                    print(f"Hue {hue:3d}: R={red:.2f} G={green:.2f} B={blue:.2f}")
                sleep(STEP_DELAY)
            completed += 1
    finally:
        led.off()


def main():
    parser = argparse.ArgumentParser(description="Fade an RGB LED through a rainbow.")
    parser.add_argument("--simulate", action="store_true", help="use fake GPIO pins")
    parser.add_argument("--cycles", type=int, default=0, help="rainbow repetitions; 0 = forever")
    args = parser.parse_args()
    if args.cycles < 0:
        parser.error("--cycles must be 0 or greater")

    try:
        from gpiozero import RGBLED
        if args.simulate:
            from gpiozero.pins.mock import MockFactory, MockPWMPin
            factory = MockFactory(pin_class=MockPWMPin)
        else:
            from gpiozero.pins.lgpio import LGPIOFactory
            factory = LGPIOFactory()
    except ImportError:
        parser.exit(1, "Missing GPIO packages. Follow the setup steps at the top of led.py.\n")

    print("Rainbow started. Press Ctrl+C to stop.")
    try:
        with RGBLED(red=17, green=27, blue=22, pwm=True,
                    active_high=True, pin_factory=factory) as led:
            rainbow(led, cycles=args.cycles, simulate=args.simulate)
    except KeyboardInterrupt:
        print("\nStopped; LED off.")
    finally:
        factory.close()


if __name__ == "__main__":
    main()

