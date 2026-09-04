import asyncio,logging,os,sys
from aiohttp import web
from config import SETTINGS
from scanner import Scanner


root=logging.getLogger()
root.setLevel(getattr(logging, SETTINGS.log_level.upper(), logging.INFO))
handler=logging.StreamHandler(sys.stdout)
handler.setLevel(root.level)
handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
root.handlers.clear()
root.addHandler(handler)

scanner=Scanner(SETTINGS)

# Fail fast on required strategy configuration instead of discovering it during
# the first coin analysis.
def validate_settings():
    required = ('scalp_leverage', 'day_leverage', 'swing_leverage')
    missing = [name for name in required if not hasattr(SETTINGS, name)]
    if missing:
        raise RuntimeError('Missing required settings: ' + ', '.join(missing))

validate_settings()
async def health(request):return web.json_response({'status':'ok','active_symbols':scanner.active,'tracked_symbols':len(scanner.market)})
async def main():
    app=web.Application();app.router.add_get('/health',health);runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'0.0.0.0',int(os.getenv('PORT',SETTINGS.port)));await site.start();
    try:await scanner.run()
    finally:await runner.cleanup()
if __name__=='__main__':asyncio.run(main())
