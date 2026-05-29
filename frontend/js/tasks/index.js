import { coreTaskMethods } from './core.js';
import { editorTaskMethods } from './editor.js';
import { debugTaskMethods } from './debug.js';

export const taskMethods = {
  ...coreTaskMethods,
  ...editorTaskMethods,
  ...debugTaskMethods,
};
