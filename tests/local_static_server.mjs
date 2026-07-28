import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..","static","intraday-analysis");
const port=Number(process.env.PORT||8033);
http.createServer((request,response)=>{
  const pathname=decodeURIComponent((request.url||"/").split("?")[0]);
  const file=path.resolve(root,pathname==="/"?"k200-market-intuition-selector.html":pathname.slice(1));
  if(!file.startsWith(root+path.sep)){response.writeHead(403).end();return}
  fs.readFile(file,(error,body)=>{response.writeHead(error?404:200,{"Content-Type":file.endsWith(".html")?"text/html;charset=utf-8":file.endsWith(".csv")?"text/csv;charset=utf-8":"application/octet-stream"});response.end(error?"not found":body)});
}).listen(port,"127.0.0.1");
