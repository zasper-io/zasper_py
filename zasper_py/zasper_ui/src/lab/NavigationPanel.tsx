import React, { useEffect, useState } from 'react';

const NavigationPanel = () => {
    const showGitPanel = () => {
        alert("showGit Panel")
    }

    const showDebugPanel = () => {
        alert("showDebug Panel")
    }

    const showSecretsPanel = () => {
        alert("showSecrets Panel")
    }

    const showSettingsPanel = () => {
        alert("showSettings Panel")
    }

    const showDatabasePanel = () => {
        alert("showDatabase Panel")
    }

    const changeActiveKey = () => {
        // setActiveTab('demo');
    }

    return (
        <div className="navigation-list">
            <button className="editor-button nav-link active" onClick={changeActiveKey}><img src="./images/editor/feather-file-text.svg" alt="" /></button>
            <button className="editor-button nav-link" onClick={showGitPanel}><img src="./images/editor/metro-flow-branch.svg" alt="" /></button>
            <button className="editor-button nav-link"><img src="./images/editor/feather-box.svg" alt="" /></button>
            <button className="editor-button nav-link" onClick={showDebugPanel}><img src="./images/editor/feather-play-circle.svg" alt="" /></button>
            <button className="editor-button nav-link" onClick={showSecretsPanel}><img src="./images/editor/feather-lock.svg" alt="" /></button>
            <button className="editor-button nav-link" onClick={showSettingsPanel}><img src="./images/editor/feather-settings.svg" alt="" /></button>
            <button className="editor-button nav-link" onClick={showDatabasePanel}><img src="./images/editor/feather-database.svg" alt="" /></button>
            <button className="editor-button nav-link"><img src="./images/editor/ionic-ios-checkmark-circle-outline.svg" alt="" /></button>
            <button className="editor-button mt-auto help-icon"><i className="fas fa-question-circle"></i></button>
        </div>
    );
}

export default NavigationPanel;
