class ZasperApp:
    name = "Zasper"
    description = "Zasper Backend Server"

    def config_file_paths(self) -> list[str]:
        path = jupyter_config_path()
        if self.config_dir not in path:
            # Insert config dir as first item.
            path.insert(0, self.config_dir)
        return path
