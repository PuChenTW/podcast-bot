import asyncio
import sys

from migrate import migrate_up, migrate_down, status

args = sys.argv[1:]
if not args or args[0] == "up":
    asyncio.run(migrate_up())
elif args[0] == "status":
    asyncio.run(status())
elif args[0] == "down":
    if len(args) < 2:
        print("Usage: python -m migrate down <target_version>", file=sys.stderr)
        sys.exit(1)
    try:
        target = int(args[1])
    except ValueError:
        print(f"Invalid version: {args[1]}", file=sys.stderr)
        sys.exit(1)
    asyncio.run(migrate_down(target_version=target))
else:
    print(f"Unknown command: {args[0]}", file=sys.stderr)
    print("Usage: python -m migrate [up|down <version>|status]", file=sys.stderr)
    sys.exit(1)
