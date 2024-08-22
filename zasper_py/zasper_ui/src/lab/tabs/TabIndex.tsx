import React, { useState, useEffect } from 'react';

export default  function TabIndex(props) {
    let tabs = props.tabs

    const handleTabClick = async (path: string) => {
        props.sendDataToParent(path);
    };
    
    return (
        <div className="main-content">
            <div id="myTabContent">
                <ul className="nav-item nav">
                    {Object.keys(tabs).map((key, index) => 
                        <li key={index} className="nav-item" role="presentation">
                            <button type="button" className="nav-link" onClick={() => handleTabClick(tabs[key].name)} >{tabs[key].name}<span className="editor-button"><i className="fas fa-times-circle"></i></span></button>
                        </li>
                    )}
                </ul>
            </div>
        </div>
    )
}
