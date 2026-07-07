/**
 * 撤销/重做管理器 — Command 模式
 */
class UndoManager {
    constructor(maxDepth = 50) {
        this.undoStack = [];
        this.redoStack = [];
        this.maxDepth = maxDepth;
    }

    /**
     * 执行一个命令并记录
     * @param {Object} command - { type, annotationId, previousState, newState, execute, undo }
     */
    execute(command) {
        if (command.execute) command.execute();
        this.undoStack.push(command);
        if (this.undoStack.length > this.maxDepth) {
            this.undoStack.shift();
        }
        this.redoStack = [];
    }

    undo() {
        if (this.undoStack.length === 0) return null;
        const cmd = this.undoStack.pop();
        if (cmd.undo) cmd.undo();
        this.redoStack.push(cmd);
        return cmd;
    }

    redo() {
        if (this.redoStack.length === 0) return null;
        const cmd = this.redoStack.pop();
        if (cmd.execute) cmd.execute();
        this.undoStack.push(cmd);
        return cmd;
    }

    canUndo() { return this.undoStack.length > 0; }
    canRedo() { return this.redoStack.length > 0; }

    clear() {
        this.undoStack = [];
        this.redoStack = [];
    }
}

// 全局实例
window.undoManager = new UndoManager();
