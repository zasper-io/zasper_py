import React, { useEffect, useState } from 'react';

import NbFileTab from './tabs/NbFileTab';
import FileTab from './tabs/FileTab';
import LauncherTab from './tabs/LauncherTab';
import SuperTab from './tabs/SuperTab';

export default function ContentPanel(props) {


    const handleKeyPress = () => {
        alert("Detected Shift+Enter");
        // if (e.key === 'Enter' && e.shiftKey) {

        //     return CodeMirror.Pass;
        // }
    }

    const onChange = React.useCallback((value, viewUpdate) => {
        console.log('value:', value);
    }, []);

    const tabToggle = () => {
    }

    const closeTab = () => {
        alert("Tab close");
    }



    useEffect(() => {
        // listContents();
    }, [])



    return (
        <div className="main-content">
            <div id="myTabContent">
                {Object.keys(props.tabs).map((key, index) => (
                    <SuperTab key={index} data={props.tabs[key]} sendDataToParent={props.sendDataToParent} />
                ))}
            </div>
        </div>
    )

}

