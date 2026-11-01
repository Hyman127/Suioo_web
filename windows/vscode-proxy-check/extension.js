const vscode=require('vscode'),fs=require('fs'),path=require('path');
exports.activate=function(context){
 const root=path.resolve(context.extensionPath,'../..'),work=path.join(root,'runtime','vscode-network-check');
 if(vscode.env.remoteName||!(vscode.workspace.workspaceFolders||[]).some(f=>path.resolve(f.uri.fsPath).toLowerCase()===work.toLowerCase()))return;
 const quote=s=>"'"+s.replace(/'/g,"''")+"'";
 const py=fs.existsSync(path.join(root,'runtime','python','python.exe'))?path.join(root,'runtime','python','python.exe'):'C:\\PythonDev\\python\\python\\python.exe';
 const output=path.join(work,'powershell-codex-version.txt');
 const terminal=vscode.window.createTerminal({name:'Suioo VS Code network verification',cwd:work});
 terminal.show(true);
 terminal.sendText(`codex --sandbox danger-full-access --ask-for-approval never --version 2>&1 | Out-File -Encoding utf8 ${quote(output)}; & ${quote(py)} -B ${quote(path.join(root,'windows','Verify-VSCodeTerminal.py'))}`);
 const timer=setInterval(()=>{const file=path.join(root,'runtime','vscode-terminal-verification.json');if(!fs.existsSync(file))return;try{const r=JSON.parse(fs.readFileSync(file,'utf8'));if(r.finished&&Date.now()/1000-r.finished<120){clearInterval(timer);terminal.dispose();vscode.commands.executeCommand('workbench.action.closeWindow');}}catch{}},1500);
 context.subscriptions.push({dispose(){clearInterval(timer);}});
};
