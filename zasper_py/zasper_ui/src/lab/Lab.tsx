
import NavigationPanel from './NavigationPanel';

import React, { useState, useEffect } from 'react';
import FileBrowser from './FileBrowser';
import "./lab.css"

import ContentPanel from './ContentPanel';
import TabIndex from './tabs/TabIndex';

interface Ifile {
    type: string,
    path: string,
    name: string,
    display: string
    load_required: boolean
}

interface IfileDict{
    [id:string]: Ifile
}

function Lab() {
    const ksfile: Ifile = {
        type: "launcher",
        path: "none",
        name: "Launcher",
        display: "d-block",
        load_required : false
    }

    const ksfileDict: IfileDict = {
       "Launcher": ksfile
    }

    const [dataFromChild, setDataFromChild] = useState<IfileDict>(ksfileDict);

    function handleDataFromChild(name, type) {
        console.log(name, type);
        if(dataFromChild[name] === undefined){
            
            const fileData: Ifile = {
                type: type,
                path: "none",
                name: name,
                display: "d-block",
                load_required: true
            }
            
            let updatedDataFromChild: IfileDict =  Object.assign({}, dataFromChild)
            for(let key in updatedDataFromChild){
                updatedDataFromChild[key]['display'] = 'd-none'
                updatedDataFromChild[key]['load_required'] = false
            }
            updatedDataFromChild[name.toString()] = fileData
            console.log(updatedDataFromChild)
            setDataFromChild(updatedDataFromChild)
        }else{
            let updatedDataFromChild: IfileDict =  Object.assign({}, dataFromChild)
            for(let key in updatedDataFromChild){
                updatedDataFromChild[key]['display'] = 'd-none'
                updatedDataFromChild[key]['load_required'] = false
            }
            updatedDataFromChild[name]['display'] = 'd-block'
            setDataFromChild(updatedDataFromChild)
        }
        console.log(dataFromChild)
    }
    
    return (
        <div>

            <div className="main-navigation">
                <NavigationPanel />
                <FileBrowser sendDataToParent={handleDataFromChild}/>
            </div>
            
            <TabIndex tabs={dataFromChild} sendDataToParent={handleDataFromChild}></TabIndex>
            <ContentPanel  tabs={dataFromChild} sendDataToParent={handleDataFromChild}></ContentPanel>
        </div>
    )
}

export default Lab;
