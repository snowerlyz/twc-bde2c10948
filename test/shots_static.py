import asyncio, sys
from playwright.async_api import async_playwright
pages = sys.argv[1].split(",") if len(sys.argv)>1 else ["", "stocks", "stock/1101", "warrants", "warrants/1101", "futures", "model", "help", "watch"]
mobile = len(sys.argv)>2 and sys.argv[2]=="m"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width":390,"height":844} if mobile else {"width":1400,"height":900}, device_scale_factor=1, is_mobile=mobile, has_touch=mobile)
        pg = await ctx.new_page()
        errs=[]
        pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for name in pages:
            await pg.goto("http://localhost:8799/#/"+name)
            await pg.wait_for_timeout(1800)
            fn = "/tmp/shot_%s%s.png" % ((name or "home").replace("/","_"), "_m" if mobile else "")
            await pg.screenshot(path=fn, full_page=True)
            print(fn)
        print("ERRORS:", errs)
        await b.close()
asyncio.run(main())
