const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const desktopRoot = path.resolve(__dirname, '..');
const projectRoot = path.resolve(desktopRoot, '..');
const isWin = process.platform === 'win32';
const virtualenvPython = path.join(projectRoot, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');
const configuredPython = process.env.QAGENT_PYTHON || process.env.PYTHON;
const python = configuredPython || (fs.existsSync(virtualenvPython) ? virtualenvPython : (isWin ? 'py' : 'python3'));
const pythonPrefix = isWin && path.basename(python).toLowerCase() === 'py' ? ['-3'] : [];

const result = spawnSync(python, [
  ...pythonPrefix,
  '-m',
  'PyInstaller',
  '--noconfirm',
  '--clean',
  '--distpath', path.join(desktopRoot, 'backend-dist'),
  '--workpath', path.join(desktopRoot, 'backend-build'),
  path.join(projectRoot, 'qagent_backend.spec')
], {
  cwd: projectRoot,
  env: {
    ...process.env,
    PYINSTALLER_CONFIG_DIR: path.join(desktopRoot, 'backend-build', 'pyinstaller-config')
  },
  shell: false,
  stdio: 'inherit'
});

if (result.error) {
  console.error(`无法启动 Python：${result.error.message}`);
  process.exit(1);
}
if (result.status !== 0) {
  console.error('后端打包失败。首次构建请确认已执行：pip install -r requirements-build.txt');
  process.exit(result.status || 1);
}

const executable = path.join(
  desktopRoot,
  'backend-dist',
  'qagent-backend',
  isWin ? 'qagent-backend.exe' : 'qagent-backend'
);
if (!fs.existsSync(executable)) {
  console.error(`后端打包结束但未找到产物：${executable}`);
  process.exit(1);
}

console.log(`后端独立运行产物：${executable}`);
