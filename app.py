import asyncio,logging,os
from aiohttp import web
from config import SETTINGS
from scanner import Scanner

logging.basicConfig(level=getattr(logging,SETTINGS.log_level.upper(),logging.INFO),format='%(asctime)s | %(levelname)s | %(name)s | %(message)s')
scanner=Scanner(SETTINGS)
async def health(request):return web.json_response({'status':'ok','active_symbols':scanner.active,'tracked_symbols':len(scanner.market)})
async def main():
    app=web.Application();app.router.add_get('/health',health);runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'0.0.0.0',int(os.getenv('PORT',SETTINGS.port)));await site.start();
    try:await scanner.run()
    finally:await runner.cleanup()
if __name__=='__main__':asyncio.run(main())
