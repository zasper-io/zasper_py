import React, { useEffect, useState } from 'react';
import "./Launcher.css"

export default function LauncherTab(props) {

    interface IKernelspec {
        name: string,
        spec: string,
        resources: string
    }

    
    const [kernelspecs, setKernelspecs] = useState({a: {name: "x", spec: "y", resources: "z"}
                                                    });
    
    const FetchData = async () => {
        const res = await fetch("http://localhost:8888/api/kernelspecs");
        const resJson = await res.json();
        setKernelspecs(resJson.kernelspecs);
        console.log(resJson.kernelspecs);
    };

    const openTerminal = async() => {
        console.log("open terminal");
        props.sendDataToParent("Terminal 1", "terminal")
    }

    useEffect(() => {
        FetchData();
    }, []);

    return (

        <div className="tab-content">
            <div className={props.data.display}>
                <h1>Notebook</h1>
                {
                    Object.keys(kernelspecs).map((key, index) => ( 
                    <div className='launcher-icon' key={index}>
                        <h2> {key}</h2>
                        {JSON.stringify(kernelspecs[key]['name'])}
                        <img src={`${kernelspecs[key]["resources"]["logo-64x64"]}`}/>
                    </div> 
                    ))
                }
                <hr></hr>
                <h1>Terminal</h1>
                <button className='launcher-icon' onClick={openTerminal}>
                    <h2>New Terminal</h2>    
                </button>
            </div>
        </div>

        )

}
