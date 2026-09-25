    if humidity < low:
        return "LOW"
    if humidity > high:
        return "HIGH"
    return "IN_RANGE"


def validate_reading(temperature, humidity):
    if temperature is None or humidity is None:
        raise ValueError("Sensor did not return a complete reading")
    temperature, humidity = float(temperature), float(humidity)
    if not math.isfinite(temperature) or not math.isfinite(humidity):
        raise ValueError("Sensor returned a non-finite reading")
    if not 0 <= humidity <= 100:
        raise ValueError(f"Humidity is outside 0-100%: {humidity}")
    return temperature, humidity


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor mushroom grow-area air humidity.")
    parser.add_argument("--simulate", action="store_true", help="use labeled made-up readings")
    parser.add_argument("--low", type=float, default=85.0, help="low RH limit; demo default 85")
    parser.add_argument("--high", type=float, default=95.0, help="high RH limit; demo default 95")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between attempts")
    parser.add_argument("--samples", type=int, default=0, help="attempts to make; 0 runs until stopped")
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x44,
                        help="SHT31 address: 0x44 (default) or 0x45")
    parser.add_argument("--log", type=Path, help="CSV file path")
    args = parser.parse_args()
    if not (math.isfinite(args.low) and math.isfinite(args.high)
            and 0 <= args.low < args.high <= 100):
        parser.error("limits must satisfy 0 <= low < high <= 100")
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be finite and greater than zero")
    if not args.simulate and args.interval < 1:
        parser.error("use an interval of at least 1 second for the hardware monitor")
    if args.samples < 0:
        parser.error("--samples must be 0 or greater")
    if args.address not in (0x44, 0x45):
        parser.error("--address must be 0x44 or 0x45")
    if args.log is None:
        name = "mushroom_humidity_simulation.csv" if args.simulate else "mushroom_humidity.csv"
        args.log = Path(__file__).resolve().parent / "logs" / name
    args.log = args.log.expanduser().resolve()
    return args


def monitor(args, sensor=None):
    mode = "SIMULATION" if args.simulate else "SHT31"
    args.log.parent.mkdir(parents=True, exist_ok=True)
    # Validate existing headers to avoid mixing incompatible CSV layouts.
    with args.log.open("a+", newline="", encoding="utf-8") as handle:
        handle.seek(0)
        existing_header = next(csv.reader(handle), None)
        if existing_header is not None and existing_header != FIELDS:
            raise ValueError("Existing log has different columns. Choose a new file with --log.")
        handle.seek(0, 2)
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if existing_header is None:
            writer.writeheader()
            handle.flush()

        print(f"Mode: {mode} | RH limits: {args.low:g}-{args.high:g}%")
        print("Limits are user settings; confirm them for your species and growth stage.")
        print(f"Log: {args.log}\nPress Ctrl+C to stop.", flush=True)
        attempt = 0
        while args.samples == 0 or attempt < args.samples:
            row = dict.fromkeys(FIELDS, "")
            row.update(timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       mode=mode, low_limit=args.low, high_limit=args.high)
            try:
                if args.simulate:
                    temperature = 22.0 + 0.1 * (attempt % 3)
                    humidity = DEMO_HUMIDITIES[attempt % len(DEMO_HUMIDITIES)]
                else:
                    temperature = sensor.temperature
                    humidity = sensor.relative_humidity
                temperature, humidity = validate_reading(temperature, humidity)
                fahrenheit = temperature * 9 / 5 + 32
                status = classify(humidity, args.low, args.high)
                row.update(temperature_c=round(temperature, 2),
                           temperature_f=round(fahrenheit, 2),
                           humidity_percent=round(humidity, 2), status=status)
                print(f"{row['timestamp_utc']} [{mode}] {humidity:5.1f}% RH | "
                      f"{temperature:.1f} C / {fahrenheit:.1f} F | {status}", flush=True)
            except (OSError, RuntimeError, ValueError, TypeError) as error:
                # Never reuse an old good value as if it were a new reading.
                row.update(status="SENSOR_ERROR", error=str(error))
                print(f"{row['timestamp_utc']} [{mode}] SENSOR_ERROR: {error}. "
                      "Check wiring, power, and moisture; retrying next interval.", flush=True)
            # Log write failures propagate so the program cannot claim to be logging.
            writer.writerow(row)
            handle.flush()
            attempt += 1
            if args.samples == 0 or attempt < args.samples:
                time.sleep(args.interval)


def main():
    args = parse_args()
    bus = None
    try:
        sensor = None
        if not args.simulate:
            if sys.platform != "linux":
                raise RuntimeError("Hardware mode needs Raspberry Pi OS. Use --simulate on Windows.")
            try:
                import adafruit_sht31d
                from adafruit_extended_bus import ExtendedI2C
            except ImportError as error:
                raise RuntimeError("Install the sensor packages using the steps at the top of this file.") from error
            bus = ExtendedI2C(1)
            sensor = adafruit_sht31d.SHT31D(bus, address=args.address)
            sensor.heater = False  # Avoid heating the sensor during normal measurements.
        monitor(args, sensor)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if bus is not None:
            bus.deinit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
