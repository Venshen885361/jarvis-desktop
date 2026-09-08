// 把 hud/ 的 PWA 複製成 www/index.html。單一來源：改 mobile.html 就好，這裡不改網頁內容。
import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("www", { recursive: true });
copyFileSync("../hud/mobile.html", "www/index.html");
copyFileSync("../hud/icon.png", "www/icon.png");
copyFileSync("../hud/manifest.webmanifest", "www/manifest.webmanifest");
console.log("www/ 已同步");
