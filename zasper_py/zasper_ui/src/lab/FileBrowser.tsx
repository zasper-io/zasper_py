import React, { useEffect, useState } from 'react';

export default function FileBrowser({ sendDataToParent }) {

    interface IContent {
        type: string,
        path: string,
        name: string
    }
    const [contents, setContents] = useState<IContent[]>([]);

    const [data, setData] = useState("");


    const directoryRightClickHandler =  (e, hey) => {
        e.preventDefault(); // prevent the default behaviour when right clicked
        console.log("Right Click");
        alert(hey);
    }


    const FetchData = async () => {
        const res = await fetch("http://localhost:8888/api/contents/");
        const resJson = await res.json();
        setContents(resJson['content']);
        // console.log(resJson['content']);
    };

    const handleFileClick = async (path: string, type: string) => {
        sendDataToParent(path, type);
    };

    const showNewFileDialog = () => {
        console.log("New file");
    }

    const createNewFile = async () => {
        let path = "abc.py";
        const res = await fetch("http://localhost:8888/api/contents", {
            method: 'POST',

            body: JSON.stringify({
                ext: '.py',
                type: 'file'
            })
        });
        FetchData();

    }

    const createNewDirectory = async () => {
        let path = "abc.py";
        const res = await fetch("http://localhost:8888/api/contents/" + path, {
            method: 'POST',
            body: JSON.stringify({
                type: 'directory'
            })
        });
        FetchData();
    }

    useEffect(() => {
        FetchData();
    }, [])

    return (
        <div className="nav-content">
            <div className="content-head">
                <h6>Files</h6>
                <div>
                    <button className='editor-button' onClick={createNewFile}><img src="./images/editor/feather-file-plus.svg" alt="" /></button>
                    <button className='editor-button' onClick={createNewDirectory}><img src="./images/editor/feather-folder-plus.svg" alt="" /></button>
                </div>
            </div>
            <div className="content-inner">
                <ul className="file-list list-unstyled">
                    {contents.map((content, index) => {
                        if (content.type === "directory") {
                            return <li key={index}><a onContextMenu={(e) => directoryRightClickHandler(e, "hi")} onClick={() => handleFileClick(content.path, content.type)}><img src="./images/editor/directory.svg" alt="" /> {content.name}<button className='editor-button-right'><img src="./images/editor/ionic-md-more.svg" alt="" /></button></a></li>
                        } else {
                            return <li key={index}><a onClick={() => handleFileClick(content.path, content.type)}><img src="./images/editor/py-icon.svg" alt="" /> {content.name}<button className='editor-button-right'><img src="./images/editor/ionic-md-more.svg" alt="" /></button></a></li>
                        }

                    }
                    )}
                </ul>
            </div>
        </div>
    )
}
